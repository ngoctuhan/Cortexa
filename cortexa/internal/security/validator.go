package security

import (
	"fmt"
	"github.com/cortexa/cortexa/internal/model"
	"regexp"
)

var (
	maxEntityNameLen  = 100
	maxAttributeLen   = 50
	maxValueLen       = 500
	allowedTypes      = map[string]bool{"person": true, "place": true, "org": true, "contact": true, "thing": true, "self": true}
	allowedAttributes = map[string]bool{
		"email": true, "phone": true, "job": true, "birthday": true,
		"address": true, "likes": true, "owns": true, "works_at": true, "relationship": true,
		"age": true, "name": true,
	}
	injectionPatterns = []*regexp.Regexp{
		regexp.MustCompile(`(?i)(ignore|forget|disregard).{0,30}(previous|above|instruction)`),
		regexp.MustCompile(`(?i)(you are|act as|pretend).{0,30}(admin|root|system)`),
		regexp.MustCompile(`(?i)system\s*prompt`),
	}
)

func ValidateExtractedFact(f model.ExtractedFact) error {
	if len(f.EntityName) == 0 || len(f.EntityName) > maxEntityNameLen {
		return fmt.Errorf("invalid entity_name length")
	}
	if !allowedTypes[f.EntityType] {
		return fmt.Errorf("unknown entity_type: %s", f.EntityType)
	}
	if !allowedAttributes[f.Attribute] {
		return fmt.Errorf("unknown attribute: %s", f.Attribute)
	}
	if len(f.Value) > maxValueLen {
		return fmt.Errorf("value too long")
	}
	for _, pat := range injectionPatterns {
		if pat.MatchString(f.Value) || pat.MatchString(f.EntityName) {
			return fmt.Errorf("potential injection detected")
		}
	}
	return nil
}
