package main

import (
	"io/ioutil"
	"strings"
	"unicode"
)

func isRuneInList(a rune, list []rune) bool {
	for _, b := range list {
		if b == a {
			return true
		}
	}
	return false
}

func cleanUp(text string, full bool) string {
	text = strings.TrimSpace(text)

	if !full {
		return text
	}

	upper := true
	var output strings.Builder
	for _, x := range strings.ToLower(text) {
		if unicode.IsLetter(x) && upper {
			output.WriteRune(unicode.ToUpper(x))
			upper = false
		} else {
			output.WriteRune(x)
		}
		if unicode.IsDigit(x) && upper {
			upper = false
		} else if isRuneInList(x, []rune{'\t', '\n', '.', '?', '!'}) {
			upper = true
		}
	}
	return output.String()
}

func readFile(filename string) string {
	content, err := ioutil.ReadFile(filename)
	if err != nil {
		panic(err)
	}
	return strings.TrimSpace(string(content))
}
