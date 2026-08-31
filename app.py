import os
import re
import secrets
from decimal import Decimal, InvalidOperation
from functools import wraps
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from markupsafe import escape
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

app = Flask(__name__)
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY é obrigatória; não use fallback em produção")

app.config.update(
    SECRET_KEY=SECRET_KEY,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production",
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
)
app.jinja_env.autoescape = True

DATABASE_URL = os.environ.get("SUPABASE_POOLER_URL") or os.environ.get("SUPABASE_DATABASE_URL") or os.environ.get("DATABASE_URL")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_STORAGE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY") or ""
SUPABASE_STORAGE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "site-images").strip().lower().replace(" ", "-")
SUPABASE_USE_STORAGE_IMAGES = os.environ.get("SUPABASE_USE_STORAGE_IMAGES", "true").lower() in {"1", "true", "yes", "on"}
ADMIN_PHONE = re.sub(r"\D", "", os.environ.get("ADMIN_PHONE", ""))
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")
DEFAULT_WHATSAPP = re.sub(r"\D", "", os.environ.get("WHATSAPP_NUMBER", "5519981895884"))
DEFAULT_PRODUCTS = [
    ("Pavê de Ovomaltine", "Creme suave com crocância de Ovomaltine.", "15.00", "Pavês", "/static/images/img1.jpeg"),
    ("Pavê de Morango com Nutella", "Morango, creme e Nutella em camadas.", "18.00", "Pavês", "/static/images/img2.jpeg"),
    ("Pavê de Nutella", "Pavê cremoso com o sabor intenso de Nutella.", "15.00", "Pavês", "/static/images/img3.jpeg"),
    ("Pavê de Oreo", "Creme delicado com pedacinhos de Oreo.", "15.00", "Pavês", "/static/images/img4.jpeg"),
    ("Pavê de KitKat", "Camadas cremosas com chocolate wafer.", "12.00", "Pavês", "/static/images/img5.jpeg"),
    ("Pavê de Sonho de Valsa", "Uma combinação cremosa com chocolate e amendoim.", "12.00", "Pavês", "/static/images/img6.jpeg"),
]


def database_connection_url():
    if not DATABASE_URL:
        raise RuntimeError("SUPABASE_DATABASE_URL não configurada")

    parts = urlsplit(DATABASE_URL)
    hostname = (parts.hostname or "").lower()
    if not (hostname.startswith("db.") and hostname.endswith(".supabase.co")):
        return DATABASE_URL

    project_ref = hostname[3 : -len(".supabase.co")]
    region = os.environ.get("SUPABASE_POOLER_REGION", "sa-east-1")
    raw_auth = parts.netloc.rsplit("@", 1)[0] if "@" in parts.netloc else "postgres"
    raw_user, separator, raw_password = raw_auth.partition(":")
    if unquote(raw_user) == "postgres":
        raw_user = f"postgres.{project_ref}"
    auth = raw_user + (separator + raw_password if separator else "")
    pooler_host = f"aws-0-{region}.pooler.supabase.com:6543"
    return urlunsplit((parts.scheme or "postgresql", f"{auth}@{pooler_host}", parts.path or "/postgres", parts.query, parts.fragment))


def db():
    return psycopg2.connect(
        database_connection_url(),
        cursor_factory=RealDictCursor,
        sslmode="require",
        connect_timeout=int(os.environ.get("DB_CONNECT_TIMEOUT", "10")),
    )


def ensure_catalog(cur):
    cur.execute("SELECT COUNT(*) AS total FROM products")
    total = cur.fetchone()["total"]
    if int(total or 0) != 0:
        return False
    for product in DEFAULT_PRODUCTS:
        cur.execute("INSERT INTO products (name, description, price, category, image_url, is_active) VALUES (%s, %s, %s, %s, %s, TRUE)", product)
    return True


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def validate_csrf():
    if request.method == "POST":
        expected = session.get("csrf_token")
        supplied = request.form.get("csrf_token", "")
        if not expected or not secrets.compare_digest(expected, supplied):
            abort(400, description="Token CSRF inválido")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Entre na sua conta para continuar.", "warning")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def normalize_phone(value):
    return re.sub(r"\D", "", value or "")


def supabase_project_url():
    if SUPABASE_URL:
        return SUPABASE_URL
    parts = urlsplit(DATABASE_URL or "")
    hostname = (parts.hostname or "").lower()
    if hostname.startswith("db.") and hostname.endswith(".supabase.co"):
        return f"https://{hostname[3 : -len('.supabase.co')]}.supabase.co"
    return ""


def storage_public_prefix():
    return f"{supabase_project_url()}/storage/v1/object/public/{quote(SUPABASE_STORAGE_BUCKET, safe='')}/"


def sanitize_image_url(value):
    candidate = str(value or "")
    if candidate.startswith("/static/images/") and ".." not in candidate and "\\" not in candidate:
        if SUPABASE_USE_STORAGE_IMAGES and storage_public_prefix():
            filename = quote(candidate.rsplit("/", 1)[-1], safe="")
            return str(escape(f"{storage_public_prefix()}{filename}"))
        return str(escape(candidate))
    if storage_public_prefix() and candidate.startswith(storage_public_prefix()):
        return str(escape(candidate))
    return "/static/images/cardapio.jpeg"


def upload_product_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    if not SUPABASE_STORAGE_KEY or not supabase_project_url():
        raise ValueError("Configure SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY para enviar imagens.")
    allowed_types = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    content_type = (file_storage.mimetype or "").lower()
    extension = allowed_types.get(content_type)
    if not extension:
        raise ValueError("Selecione uma imagem JPG, PNG ou WEBP.")
    image_data = file_storage.read()
    if not image_data:
        raise ValueError("O arquivo de imagem está vazio.")
    object_path = f"products/{secrets.token_hex(16)}{extension}"
    bucket = quote(SUPABASE_STORAGE_BUCKET, safe="")
    path = quote(object_path, safe="/")
    endpoint = f"{supabase_project_url()}/storage/v1/object/{bucket}/{path}"
    upload_request = Request(
        endpoint,
        data=image_data,
        headers={
            "Authorization": f"Bearer {SUPABASE_STORAGE_KEY}",
            "apikey": SUPABASE_STORAGE_KEY,
            "Content-Type": content_type,
            "Cache-Control": "31536000",
            "x-upsert": "false",
        },
        method="POST",
    )
    try:
        with urlopen(upload_request, timeout=20) as response:
            if response.status not in {200, 201}:
                raise ValueError("O Storage recusou o upload da imagem.")
    except (HTTPError, URLError, TimeoutError) as error:
        detail = getattr(error, "reason", "erro de comunicação")
        raise ValueError(f"Não foi possível enviar a imagem para o Storage: {detail}") from error
    return f"{supabase_project_url()}/storage/v1/object/public/{bucket}/{path}"


def money(value):
    return f"R$ {Decimal(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def calculate_total(subtotal):
    return Decimal(subtotal)


def product_form_data(form):
    name = form.get("name", "").strip()
    description = form.get("description", "").strip()
    category = form.get("category", "").strip()
    image_url = form.get("image_url", "").strip() or "/static/images/cardapio.jpeg"
    try:
        price = Decimal(form.get("price", "").replace(",", "."))
        if price < 0:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        raise ValueError("Preço inválido.")
    if len(name) < 2:
        raise ValueError("Informe um nome válido para o produto.")
    if len(category) < 2:
        raise ValueError("Informe uma categoria válida.")
    if len(description) > 500:
        raise ValueError("A descrição deve ter no máximo 500 caracteres.")
    allowed_local = image_url.startswith("/static/images/") and ".." not in image_url and "\\" not in image_url
    allowed_storage = storage_public_prefix() and image_url.startswith(storage_public_prefix())
    if not (allowed_local or allowed_storage):
        image_url = "/static/images/cardapio.jpeg"
    return name, description, price, category, image_url


app.jinja_env.filters["money"] = money


def current_user():
    if not session.get("user_id"):
        return None
    try:
        with db() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, name, phone, is_admin FROM users WHERE id = %s", (session["user_id"],))
            return cur.fetchone()
    except psycopg2.Error:
        session.clear()
        return None


@app.context_processor
def inject_globals():
    return {"current_user": current_user(), "cart": session.get("cart", {})}


@app.route("/", methods=["GET"])
def index():
    settings = {"whatsapp_number": DEFAULT_WHATSAPP, "store_open": True}
    products = []
    try:
        with db() as conn, conn.cursor() as cur:
            if ensure_catalog(cur):
                conn.commit()
            cur.execute("SELECT id, name, description, price, category, image_url, is_active FROM products WHERE COALESCE(is_active, TRUE) = TRUE ORDER BY category, id")
            products = cur.fetchall()
            cur.execute("SELECT whatsapp_number, store_open FROM store_settings ORDER BY id LIMIT 1")
            settings.update(cur.fetchone() or {})
    except psycopg2.Error:
        flash("O cardápio está temporariamente indisponível. Verifique a conexão com o Supabase.", "error")
    for product in products:
        product["image_url"] = sanitize_image_url(product.get("image_url"))
    cart = session.get("cart", {})
    cart_products = {str(product["id"]): product for product in products if str(product["id"]) in cart}
    cart_subtotal = sum(Decimal(cart_products[key]["price"]) * quantity for key, quantity in cart.items() if key in cart_products)
    cart_total = calculate_total(cart_subtotal)
    categories = []
    for product in products:
        if product["category"] not in categories:
            categories.append(product["category"])
    return render_template("index.html", products=products, categories=categories, settings=settings, cart_products=cart_products, cart_subtotal=cart_subtotal, cart_total=cart_total)


@app.route("/cadastro", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = normalize_phone(request.form.get("phone"))
        password = request.form.get("password", "")
        if len(name) < 3 or len(phone) < 10 or len(password) < 8:
            flash("Informe nome, WhatsApp válido e senha com pelo menos 8 caracteres.", "error")
            return render_template("login.html", mode="register")
        is_admin = bool(ADMIN_PHONE and phone == ADMIN_PHONE and request.form.get("admin_key") == ADMIN_KEY)
        try:
            with db() as conn, conn.cursor() as cur:
                cur.execute("INSERT INTO users (name, phone, password_hash, is_admin) VALUES (%s, %s, %s, %s) RETURNING id", (name, phone, generate_password_hash(password), is_admin))
                user_id = cur.fetchone()["id"]
                conn.commit()
        except psycopg2.errors.UniqueViolation:
            flash("Este WhatsApp já está cadastrado.", "error")
            return render_template("login.html", mode="register")
        session.clear()
        session["user_id"] = user_id
        session["is_admin"] = is_admin
        return redirect(url_for("index"))
    return render_template("login.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone = normalize_phone(request.form.get("phone"))
        password = request.form.get("password", "")
        with db() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE phone = %s", (phone,))
            user = cur.fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            flash("WhatsApp ou senha inválidos.", "error")
            return render_template("login.html", mode="login")
        session.clear()
        session["user_id"] = user["id"]
        session["is_admin"] = user["is_admin"]
        return redirect(request.args.get("next") or url_for("index"))
    return render_template("login.html", mode="login")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/carrinho/adicionar/<int:product_id>", methods=["POST"])
@login_required
def add_to_cart(product_id):
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name, price, is_active FROM products WHERE id = %s", (product_id,))
        product = cur.fetchone()
    if not product or not product["is_active"]:
        abort(404)
    cart = session.setdefault("cart", {})
    key = str(product_id)
    cart[key] = int(cart.get(key, 0)) + max(1, min(int(request.form.get("quantity", 1)), 99))
    session.modified = True
    flash(f"{product['name']} entrou no carrinho.", "success")
    return redirect(request.referrer or url_for("index"))


@app.route("/carrinho/atualizar", methods=["POST"])
@login_required
def update_cart():
    cart = {}
    for key, value in request.form.items():
        if key.startswith("qty_"):
            try:
                quantity = max(0, min(int(value), 99))
                if quantity:
                    cart[key[4:]] = quantity
            except ValueError:
                continue
    session["cart"] = cart
    return redirect(url_for("index") + "#carrinho")


@app.route("/pedido", methods=["POST"])
@login_required
def create_order():
    cart = session.get("cart", {})
    if not cart:
        flash("Seu carrinho está vazio.", "warning")
        return redirect(url_for("index"))
    with db() as conn, conn.cursor() as cur:
        ids = [int(k) for k in cart]
        cur.execute("SELECT * FROM products WHERE id = ANY(%s) AND is_active = TRUE", (ids,))
        products = {str(row["id"]): row for row in cur.fetchall()}
        user = current_user()
        if not user or len(products) != len(cart):
            flash("Um item do carrinho não está mais disponível.", "error")
            return redirect(url_for("index"))
        subtotal = sum(Decimal(products[key]["price"]) * quantity for key, quantity in cart.items())
        cur.execute("SELECT whatsapp_number FROM store_settings ORDER BY id LIMIT 1")
        settings = cur.fetchone() or {"whatsapp_number": DEFAULT_WHATSAPP}
        total = calculate_total(subtotal)
        cur.execute("INSERT INTO orders (user_id, user_name, user_phone, total_amount, status) VALUES (%s,%s,%s,%s,'em_andamento') RETURNING id", (user["id"], user["name"], user["phone"], total))
        order_id = cur.fetchone()["id"]
        for key, quantity in cart.items():
            product = products[key]
            unit_price = Decimal(product["price"])
            cur.execute("INSERT INTO order_items (order_id, product_id, product_name, quantity, unit_price, subtotal) VALUES (%s,%s,%s,%s,%s,%s)", (order_id, product["id"], product["name"], quantity, unit_price, unit_price * quantity))
        conn.commit()
    session["cart"] = {}
    lines = [f"Pedido #{order_id}", f"Nome: {user['name']}", f"Telefone: {user['phone']}", "", "Compra:"]
    lines += [f"{products[key]['name']} x {quantity}" for key, quantity in cart.items()]
    lines += [f"Valor total da compra: {money(total)}"]
    whatsapp = re.sub(r"\D", "", settings.get("whatsapp_number") or DEFAULT_WHATSAPP)
    return redirect(f"https://wa.me/{whatsapp}?text={quote(chr(10).join(lines))}")


@app.route("/admin")
@admin_required
def admin():
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT o.*, COALESCE(string_agg(oi.product_name || ' x ' || oi.quantity, ', ' ORDER BY oi.id), '') AS items FROM orders o LEFT JOIN order_items oi ON oi.order_id = o.id WHERE o.status IN ('em_andamento','confirmado') GROUP BY o.id ORDER BY o.created_at DESC")
        orders = cur.fetchall()
        cur.execute("SELECT * FROM products ORDER BY category, name")
        products = cur.fetchall()
    return render_template("admin.html", orders=orders, products=products)


@app.route("/admin/pedido/<int:order_id>/<status>", methods=["POST"])
@admin_required
def update_order(order_id, status):
    if status not in {"confirmado", "finalizado"}:
        abort(400)
    with db() as conn, conn.cursor() as cur:
        cur.execute("UPDATE orders SET status = %s WHERE id = %s", (status, order_id))
        conn.commit()
    return redirect(url_for("admin"))


@app.route("/admin/produto/adicionar", methods=["POST"])
@admin_required
def add_product():
    try:
        name, description, price, category, image_url = product_form_data(request.form)
        image_url = upload_product_image(request.files.get("image")) or image_url
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("admin"))
    with db() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO products (name, description, price, category, image_url, is_active) VALUES (%s, %s, %s, %s, %s, TRUE)", (name, description, price, category, image_url))
        conn.commit()
    flash("Produto adicionado ao cardápio.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/produto/<int:product_id>", methods=["POST"])
@admin_required
def update_product(product_id):
    try:
        name, description, price, category, image_url = product_form_data(request.form)
        image_url = upload_product_image(request.files.get("image")) or image_url
    except ValueError as error:
        flash(str(error), "error")
        return redirect(url_for("admin"))
    active = request.form.get("is_active") == "on"
    with db() as conn, conn.cursor() as cur:
        cur.execute("UPDATE products SET name = %s, description = %s, price = %s, category = %s, image_url = %s, is_active = %s WHERE id = %s", (name, description, price, category, image_url, active, product_id))
        conn.commit()
    flash("Produto atualizado.", "success")
    return redirect(url_for("admin"))


@app.route("/admin/produto/<int:product_id>/remover", methods=["POST"])
@admin_required
def remove_product(product_id):
    with db() as conn, conn.cursor() as cur:
        cur.execute("UPDATE products SET is_active = FALSE WHERE id = %s", (product_id,))
        conn.commit()
    flash("Produto removido do cardápio. O histórico de pedidos foi preservado.", "success")
    return redirect(url_for("admin"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
