package security

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"

	"golang.org/x/crypto/hkdf"
)

// Errors returned by crypto operations.
var (
	ErrInvalidCiphertext = errors.New("invalid ciphertext: too short")
)

// Crypto handles encryption and decryption operations using AES-GCM.
type Crypto struct {
	masterKey []byte
}

// NewCrypto creates a new Crypto instance from a hexadecimal master key.
// The master key must be a 64-character hexadecimal string (32 bytes).
func NewCrypto(masterKeyHex string) (*Crypto, error) {
	key, err := hex.DecodeString(masterKeyHex)
	if err != nil {
		return nil, err
	}
	if len(key) != 32 {
		return nil, errors.New("master key must be 32 bytes (64 hex characters)")
	}
	return &Crypto{masterKey: key}, nil
}

// deriveKey derives a tenant-specific encryption key using HKDF-SHA256.
func (c *Crypto) deriveKey(tenantID string) []byte {
	hkdf := hkdf.New(sha256.New, c.masterKey, []byte(tenantID), nil)
	key := make([]byte, 32)
	io.ReadFull(hkdf, key)
	return key
}

// EncryptValue encrypts a plaintext value using AES-GCM with a tenant-specific key.
// The returned ciphertext includes the nonce prepended to the encrypted data.
func (c *Crypto) EncryptValue(plaintext, tenantID string) ([]byte, error) {
	tenantKey := c.deriveKey(tenantID)
	block, err := aes.NewCipher(tenantKey)
	if err != nil {
		return nil, err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	nonce := make([]byte, gcm.NonceSize())
	if _, err = io.ReadFull(rand.Reader, nonce); err != nil {
		return nil, err
	}
	ciphertext := gcm.Seal(nonce, nonce, []byte(plaintext), nil)
	return ciphertext, nil
}

// DecryptValue decrypts a ciphertext value using AES-GCM with a tenant-specific key.
// The ciphertext must have the nonce prepended to the encrypted data.
func (c *Crypto) DecryptValue(ciphertext []byte, tenantID string) (string, error) {
	tenantKey := c.deriveKey(tenantID)
	block, err := aes.NewCipher(tenantKey)
	if err != nil {
		return "", err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return "", err
	}
	nonceSize := gcm.NonceSize()
	if len(ciphertext) < nonceSize {
		return "", ErrInvalidCiphertext
	}
	nonce, ciphertext := ciphertext[:nonceSize], ciphertext[nonceSize:]
	plaintext, err := gcm.Open(nil, nonce, ciphertext, nil)
	if err != nil {
		return "", err
	}
	return string(plaintext), nil
}

// ValueHash returns the SHA256 hash of a value as a hexadecimal string.
// This is used for deduplication and comparison of encrypted values.
func ValueHash(value string) string {
	h := sha256.Sum256([]byte(value))
	return hex.EncodeToString(h[:])
}
