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


def search_customers(name_contains: str, limit: int = 10) -> list[dict]:
    """SEARCH: customers whose name contains the given text, case-insensitive."""
    return run_query(
        """ 
        SELECT id, name, email, created_at
        FROM customers
        WHERE name ILIKE %s
        ORDER BY name
        LIMIT %s
        """,
        # The % wildcards belong in the PARAMETER, not the SQL string.
        # psycopg escapes the value, so a name of "'; DROP TABLE--" is
        # searched for literally. Writing ILIKE '%{name}%' as an f-string
        # would be the injection hole this whole design avoids.
        (f"%{name_contains}%", limit),
    )

def list_products(in_stock_only: bool = False, limit: int = 20) -> list[dict]:
    """FILTERED LIST: products with price and current stock level."""
    sql = """                                                                  
        SELECT id, name, price_cents, stock
        FROM products
        WHERE TRUE
    """
    params = []

    # No param appended here — the condition is a fixed literal, not a
    # value. The WHERE TRUE + append pattern handles both kinds.
    if in_stock_only:
        sql += " AND stock > 0"

    sql += " ORDER BY name LIMIT %s"
    params.append(limit)

    return run_query(sql, tuple(params))

def top_customers(limit: int = 5) -> list[dict]:
    """AGGREGATE: customers ranked by total spend, ignoring cancelled orders."""
    return run_query(
        """
        SELECT c.name AS customer,
                COUNT(o.id)                      AS order_count,
                SUM(o.quantity)                  AS units_bought,
                SUM(o.quantity * p.price_cents)  AS spend_cents
        FROM orders o
        JOIN customers c ON c.id = o.customer_id
        JOIN products  p ON p.id = o.product_id
        WHERE o.status <> 'cancelled'
        GROUP BY c.name
        ORDER BY spend_cents DESC
        LIMIT %s
        """,
        (limit,),
    )









