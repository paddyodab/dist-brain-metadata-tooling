def list_line_items(order_id):
    """List line items.

    @intent Returns the LineItems for an Order, sorted by the DropDate.
    @param order_id int
    @returns list[LineItem]
    """
    return []


def save_ship_window(order_id, window):
    """Persist a ship window.

    @intent ShipWindow for an Order is stored so Fulfillment can plan the DropDate.
    @param order_id int
    @param window ShipWindow
    @returns bool
    @raises ValueError when the ShipWindow is missing
    """
    if not window:
        raise ValueError("window required")
    return True


def build_order_view(order_id):
    """Adapter to frontend.

    @intent assembles the frontend OrderView payload from the Order and LineItems.
    @flag enable_order_notifications
    @adapts frontend/ui.py#OrderView
    @param order_id int
    @returns dict
    """
    return {"order_id": order_id, "line_items": list_line_items(order_id)}
