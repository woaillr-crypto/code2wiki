package order

import "github.com/gin-gonic/gin"

// Handler exposes order HTTP endpoints.
type Handler struct {
	svc *Service
}

func (h *Handler) Register(r *gin.Engine) {
	r.POST("/api/order/create", h.Create)
	r.GET("/api/order/:id", h.Get)
	r.PUT("/api/order/:id/status", h.UpdateStatus)
}

func (h *Handler) Create(c *gin.Context) {
	// db.Transaction(func(tx *gorm.DB) error { ... })
}

func (h *Handler) Get(c *gin.Context) {}

func (h *Handler) UpdateStatus(c *gin.Context) {}
