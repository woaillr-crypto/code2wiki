package order

import "sync"

// Service implements the order business logic.
type Service struct {
	mu sync.Mutex
}

func (s *Service) Create(input map[string]any) (uint64, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return 0, nil
}

func (s *Service) Get(id uint64) (*Order, error) {
	return nil, nil
}
