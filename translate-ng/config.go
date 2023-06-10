package main

import (
	"strings"

	"github.com/go-ini/ini"
)

type cfgV struct {
	s string
	i int
	b bool
}

// cfgLoad loads the config file
func cfgLoad(filename string) *ini.File {
	cfg, err := ini.Load(filename)
	if err != nil {
		panic(err)
	}
	return cfg
}

func populateConfigDB(db *map[string]cfgV, fileName string, section string) {
	(*db) = make(map[string]cfgV)
	iniFile := cfgLoad(fileName)
	hash := iniFile.Section(section).Keys()
	for _, key := range hash {
		keyName := key.Name()
		k := iniFile.Section(section).Key(keyName)
		(*db)[keyName] = cfgV{s: k.MustString(""), i: k.MustInt(-1), b: k.MustBool(false)}
	}
}

// cfgInt returns the value of an int cfg variable or -1 if it doesn't exist
// and puts it in cache
func cfgInt(k string) int {
	if v, ok := configDB[k]; ok {
		return v.i
	}
	return -1
}

// cfgString returns the value of a string cfg variable or "" if it doesn't exist
func cfgString(k string) string {
	if v, ok := configDB[k]; ok {
		return v.s
	}
	return ""
}

// cfgBool returns the value of a boolean cfg variable or false if it doesn't exist
func cfgBool(k string) bool {
	if v, ok := configDB[k]; ok {
		return v.b
	}
	return false
}

func cfgStringList(k string) []string {
	if v, ok := configDB[k]; ok {
		return strings.Split(v.s, ",")
	}
	return []string{}
}
