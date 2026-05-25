package lambdalog

import (
	"encoding/json"
	"io"
	"log"
	"os"
	"time"
)

type coldStartLog struct {
	Timestamp string `json:"timestamp"`
	Level     string `json:"level"`
	Message   string `json:"message"`
	Service   string `json:"service"`
	Version   string `json:"version"`
	ColdStart bool   `json:"cold_start"`
}

func PrintColdStart(service, codeVersion string) {
	if err := WriteColdStart(os.Stdout, service, codeVersion, time.Now().UTC()); err != nil {
		log.Printf("level=info message=%q service=%s version=%s cold_start=true", "lambda cold start", service, codeVersion)
	}
}

func WriteColdStart(writer io.Writer, service, codeVersion string, now time.Time) error {
	return json.NewEncoder(writer).Encode(coldStartLog{
		Timestamp: now.UTC().Format(time.RFC3339Nano),
		Level:     "info",
		Message:   "lambda cold start",
		Service:   service,
		Version:   codeVersion,
		ColdStart: true,
	})
}
