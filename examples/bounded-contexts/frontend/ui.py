from backend.orders import build_order_view


def OrderView(props):
    """Order page.

    @intent draws the OrderView for the CheckoutFlow using data from the backend adapter.
    @flag enable_order_notifications
    @props props
    @renders JSX
    """
    payload = build_order_view(props["order_id"])
    return {"component": "OrderView", "payload": payload}


def LineItemRow(props):
    """Line item row.

    @intent draws a LineItemRow inside an OrderView.
    @props props
    @renders JSX
    """
    return {"component": "LineItemRow", "item": props["item"]}


def CartBadge(count):
    """Cart badge.

    @intent Renders a CartBadge and a WishlistBadge showing the cart and wishlist counts.
    @props count int
    @renders JSX
    """
    return {"component": "CartBadge", "count": count}
