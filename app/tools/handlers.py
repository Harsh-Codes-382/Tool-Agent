from app.db import run_query

def get_customer(customer_id: int) -> list[dict]:
    """LOOKUP: one customer by id."""
    return run_query(
        "SELECT id, name, email, created_at FROM customers WHERE id = %s",
        (customer_id,),
    )


def list_orders(customer_id: int = None, status: str = None, limit: int = 10) -> list[dict]:
    """FILTERED LIST: orders, optionally narrowed by customer and/or status."""
    sql = """
        SELECT o.id, o.customer_id, o.quantity, o.status, o.created_at,
                c.name AS customer, p.name AS product, p.price_cents
        FROM orders o
        JOIN customers c ON c.id = o.customer_id
        JOIN products  p ON p.id = o.product_id
        WHERE TRUE
    """
    params = []

    if customer_id is not None:
        sql += " AND o.customer_id = %s"
        params.append(customer_id)

    if status is not None:
        sql += " AND o.status = %s"
        params.append(status)

    sql += " ORDER BY o.created_at DESC LIMIT %s"
    params.append(limit)

    return run_query(sql, tuple(params))


def revenue_by_product() -> list[dict]:
    """AGGREGATE: revenue per product, ignoring cancelled orders."""
    return run_query(
        """
        SELECT p.name AS product,
                SUM(o.quantity)                  AS units_sold,
                SUM(o.quantity * p.price_cents)  AS revenue_cents
        FROM orders o
        JOIN products p ON p.id = o.product_id
        WHERE o.status <> 'cancelled'
        GROUP BY p.name
        ORDER BY revenue_cents DESC
        """
    )





