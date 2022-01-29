package main

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/go-resty/resty/v2"
)

type translationRequest struct {
	LangFrom string
	LangTo   string
	Proxy    string
	Text     string
}

const proxyErrorSentinel = "_proxy_error_sentinel_"

func makeRequest(ctx context.Context, r translationRequest, resultsChan chan<- string) {
	var proxyErrorCount int
	for {
		select {
		case <-ctx.Done():
			// we have been told to die
			return
		default:
			client := resty.New()
			client.SetProxy("http://" + r.Proxy).SetTimeout(time.Duration(cfgInt("translate_http_timeout")) * time.Second)
			resp, err := client.R().
				SetQueryString("client=gtx&dt=t&ie=UTF-8&oe=UTF-8&otf=1&ssel=0&tsel=0&kc=7&dt=at&dt=bd&dt=ex&dt=ld&dt=md&dt=qca&dt=rw&dt=rm&dt=ss").
				SetQueryParams(map[string]string{"sl": r.LangFrom, "tl": r.LangTo, "q": r.Text}).
				SetHeader("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/97.0.4692.71 Safari/537.36").
				SetHeader("Accept", "*/*").
				SetHeader("Accept-Language", "en-US,en;q=0.9,es;q=0.8").
				SetHeader("Content-Type", "application/x-www-form-urlencoded;charset=UTF-8").
				SetHeader("Origin", "https://translate.google.com").
				SetHeader("Referer", "https://translate.google.com/").
				ForceContentType("application/json").
				SetResult([][][]string{}).
				Get("https://translate.googleapis.com/translate_a/single")

			if err == nil || strings.Contains(fmt.Sprint(err), "json: cannot unmarshal") {
				// we haven't received a timeout or anything like that
				if strings.HasPrefix(resp.String(), "<") {
					// if the response starts with < it's because we have received an html page with a quota error
					// retrying wouldn't do any good so kill this goroutine
					resultsChan <- proxyErrorSentinel
					return
				}
				// send the result through the channel and kill this goroutine
				resultsChan <- cleanUp(parseTranslation(*resp.Result().(*[][][]string)), false)
				return
			} else {
				proxyErrorCount++
				if proxyErrorCount >= cfgInt("translate_http_retries") {
					// send a failure message through the channel and kill this goroutine
					resultsChan <- proxyErrorSentinel
					return
				}
			}
		}
	}
}

// parseTranslation parses the response json, where the translation is split
// across several fields
func parseTranslation(arr [][][]string) string {
	var output strings.Builder
	for _, x := range arr[0] {
		if x[0] != "" {
			output.WriteString(x[0])
		}
	}
	return output.String()
}
