package order

// Order is the persisted order row.
type Order struct {
	ID     uint64
	UserID uint64
	Amount uint64
	Status string
}

func (Order) TableName() string {
	return "t_order"
}
