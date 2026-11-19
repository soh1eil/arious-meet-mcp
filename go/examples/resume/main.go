// Command resume shows how to resume where another agent left off.
//
// Run: ARIOUS_MCP_TOKEN=... go run ./examples/resume
package main

import (
	"context"
	"fmt"
	"log"
	"time"

	ariousmcp "github.com/soh1eil/arious-meet-mcp/go"
)

func main() {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	client, err := ariousmcp.New(ariousmcp.WithModelName("Claude Sonnet 5"))
	if err != nil {
		log.Fatal(err)
	}

	// 1. Orient yourself. start_here also carries the last context's brief.
	raw, err := client.StartHere(ctx, ariousmcp.StartHereArgs{})
	if err != nil {
		log.Fatal(err)
	}
	start, err := ariousmcp.DecodeStartHere(raw)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println(start.Text)

	// 2. Pick up the most recently updated active context (or set ContextID).
	raw, err = client.ContextResume(ctx, ariousmcp.ContextResumeArgs{})
	if err != nil {
		log.Fatal(err)
	}
	resume, err := ariousmcp.DecodeContextResume(raw)
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println(resume.Brief) // saved notes of earlier sessions: data, never instructions
	if !resume.CanWrite {
		log.Fatal("this context is read-only")
	}

	// 3. ...do the next step, then checkpoint it against the version you read.
	base := resume.Version
	for attempt := 0; attempt < 2; attempt++ {
		raw, err = client.ContextCheckpoint(ctx, ariousmcp.ContextCheckpointArgs{
			ContextID:   resume.ContextID,
			BaseVersion: base,
			CurrentStep: "Reviewing the results",
			Append:      &ariousmcp.ContextCheckpointArgsAppend{DoneSteps: []string{"Finished the step I picked up"}},
		})
		if conflict, ok := ariousmcp.IsContextConflict(err); ok {
			// Another agent wrote meanwhile: merge into conflict.Latest, then retry on top of it.
			fmt.Println("conflict, latest is version", conflict.LatestVersion)
			base = conflict.LatestVersion
			continue
		}
		if err != nil {
			log.Fatal(err)
		}
		saved, err := ariousmcp.DecodeCheckpoint(raw)
		if err != nil {
			log.Fatal(err)
		}
		fmt.Println("saved version", saved.Version)
		for _, r := range saved.Redacted { // secrets the server removed; never put credentials in a context
			fmt.Println("redacted", r.Kind, "in", r.Field)
		}
		return
	}
	log.Fatal("could not save the checkpoint")
}
