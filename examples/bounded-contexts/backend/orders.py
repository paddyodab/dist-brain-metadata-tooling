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


def validate_ship_window(window):
    """Validate a proposed ship window.

    @intent Rejects a ShipWindow that cannot be fulfilled before the DropDate.
    @param window ShipWindow
    @returns bool
    @raises ValueError when the ShipWindow is empty or the DropDate has passed
    """
    if not window:
        raise ValueError("window required")
    return True


def compute_drop_date(order_id, line_items):
    """Compute the earliest DropDate for an order.

    @intent Computes the DropDate for an Order from its LineItems so Fulfillment can schedule picking.
    @param order_id int
    @param line_items list[LineItem]
    @returns DropDate
    @raises ValueError when no LineItems are provided
    """
    if not line_items:
        raise ValueError("at least one line item required")
    return None


def notify_fulfillment(order_id, drop_date):
    """Notify fulfillment of a scheduled drop date.

    @intent Notifies Fulfillment that an Order is ready to ship on the given DropDate.
    @feature enable_order_notifications
    @param order_id int
    @param drop_date DropDate
    @returns bool
    """
    return True
