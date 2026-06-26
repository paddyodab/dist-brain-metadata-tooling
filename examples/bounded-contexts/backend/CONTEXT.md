# Backend context

## Glossary

### ShipWindow
A calendar window during which an order is expected to ship to the customer.

### LineItem
A single row in an order, representing one SKU, quantity, and price.

### Order
The persisted aggregate of a customer's purchase. Owned by the backend context; different from the frontend Order view model.

### Fulfillment
The process of turning a paid order into a delivered package, spanning picking, packing, and carrier hand-off.

### DropDate
The earliest calendar date an order is expected to ship to the customer.

### OrderView
The backend view-model shape sent to the frontend to render an order summary.
