package main

import "fmt"

// A mutation has already returned from durable storage when its receipt is written.
// Losing that receipt leaves the caller unable to determine the outcome safely.
func mutationResponseError(id string, err error) error {
	if err == nil {
		return nil
	}
	if id == "" {
		return fmt.Errorf("UNKNOWN OUTCOME: local plan may be partially applied; inspect durable history for every affected fact ID before deciding whether to retry; do not replay the plan automatically")
	}
	return fmt.Errorf("UNKNOWN OUTCOME: response unavailable for fact %s; inspect durable history with memcue history %s before deciding whether to retry", id, id)
}
