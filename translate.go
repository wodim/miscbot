package main

import (
	"context"
	"fmt"
	"os"
	"strings"
	"time"
)

var configDB map[string]cfgV

const separatorSentinel = "__TRANSLATE_NG_SENTINEL__"

func main() {
	populateConfigDB(&configDB, "config.ini", "bot")

	if len(os.Args) < 3 {
		fmt.Printf("Not enough parameters.\nUsage: %v file.txt en,de,fr,es,zh\n", os.Args[0])
		os.Exit(1)
	}

	text := readFile(os.Args[1])
	/* since the results are read from the same input file, this is here so if this script dies
	and no output file has been written the python script detects that this process has failed and
	doesn't try to parse back the original text */
	os.Remove(os.Args[1])

	// read the list of languages from the command arguments
	languages := strings.Split(os.Args[2], ",")
	source := languages[0]
	results := cleanUp(text, true) + separatorSentinel + source + separatorSentinel
	for _, language := range languages[1:] {
		text = cleanUp(text, true)

	refreshProxyList:
		// read and parse the file with all the proxies
		proxyList := strings.Split(readFile("proxies.txt"), "\n")
		proxyCount := len(proxyList)
		if proxyCount == 0 {
			fmt.Printf("No proxies! Waiting 5 seconds.")
			time.Sleep(5 * time.Second)
			goto refreshProxyList
		}

		// create the channel where the results will be received and spawn all the goroutines
		resultChan := make(chan string)
		ctx, cancel := context.WithCancel(context.Background())
		for _, proxy := range proxyList {
			go makeRequest(ctx, translationRequest{source, language, proxy, text}, resultChan)
		}

		for {
			// this blocks until a new result is received from the channel
			newLine := <-resultChan
			if newLine == proxyErrorSentinel {
				// this goroutine has failed permanently, so decrement the counter of alive goroutines
				proxyCount--
				if proxyCount == 0 {
					// all goroutines have died, which means all http requests have failed.
					// we have to reread the proxy list and start over
					cancel()
					goto refreshProxyList
				}
			} else {
				// we have received a translation, so tell the remaining goroutines to die,
				// append the result to the output string, and continue with the next language
				cancel()
				text = newLine
				results += newLine + separatorSentinel + language + separatorSentinel
				source = language
				break
			}
		}
	}

	fmt.Printf("Done translating. Saving to %s\n", os.Args[1])
	os.WriteFile(os.Args[1], []byte(results), 0644)
}
