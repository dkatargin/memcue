package extract

// Expansion and Translated only decode old dream answers so callers can refuse
// obsolete auxiliary work explicitly. Current prompts and schemas never emit them.
type Expansion struct {
	ID      string   `json:"id"`
	Queries []string `json:"queries"`
}
type Translated struct {
	ID          string `json:"id"`
	Translation string `json:"translation"`
}
