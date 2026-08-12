DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
    id          SERIAL PRIMARY KEY,
    name        TEXT        NOT NULL,
    email       TEXT        NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE products (
    id          SERIAL PRIMARY KEY,
    name        TEXT           NOT NULL,
    price_cents INTEGER        NOT NULL CHECK (price_cents >= 0),
    stock       INTEGER        NOT NULL DEFAULT 0
);

CREATE TABLE orders (
    id           SERIAL PRIMARY KEY,
    customer_id  INTEGER     NOT NULL REFERENCES customers(id),
    product_id   INTEGER     NOT NULL REFERENCES products(id),
    quantity     INTEGER     NOT NULL CHECK (quantity > 0),
    status       TEXT        NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','shipped','delivered','cancelled')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO customers (name, email) VALUES
    ('Acme Corp',    'ops@acme.example'),
    ('Globex Inc',   'buy@globex.example'),
    ('Initech',      'orders@initech.example');

INSERT INTO products (name, price_cents, stock) VALUES
    ('Widget',   1999, 100),
    ('Gadget',   4999,  40),
    ('Gizmo',   12999,  10);

INSERT INTO orders (customer_id, product_id, quantity, status) VALUES
    (1, 1, 3, 'delivered'),
    (1, 2, 1, 'pending'),
    (2, 3, 2, 'shipped'),
    (3, 1, 5, 'pending'),
    (2, 1, 1, 'cancelled');

