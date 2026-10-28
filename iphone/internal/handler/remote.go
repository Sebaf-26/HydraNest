package handler

// HydraNest: a phone's remote (Tailscale) address.

import (
	"net/http"

	"github.com/labstack/echo/v5"
)

// GET /api/devices/:udid/remote
func (h *Handler) getRemote(c *echo.Context) error {
	access, err := h.svc.RemoteAccess(c.Request().Context(), c.Param("udid"))
	if err != nil {
		return err
	}
	return c.JSON(http.StatusOK, access)
}

// PUT /api/devices/:udid/remote
func (h *Handler) setRemote(c *echo.Context) error {
	var body struct {
		Address string `json:"address"`
	}
	if err := echo.BindBody(c, &body); err != nil {
		return err
	}
	access, err := h.svc.SetRemoteAddress(c.Request().Context(), c.Param("udid"), body.Address)
	if err != nil {
		return err
	}
	return c.JSON(http.StatusOK, access)
}
