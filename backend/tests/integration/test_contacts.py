"""Integration tests for the contacts module (CRUD + vCard import/export)."""

from app.services.contact_service import parse_vcard, serialize_vcard


class TestContactsCrud:
    async def test_create_get_list(self, client):
        resp = await client.post(
            "/api/v1/contacts",
            json={"name": "Ada Lovelace", "email": "Ada@Example.com", "company": "Analytical Inc."},
        )
        assert resp.status_code == 201
        created = resp.json()
        assert created["email"] == "ada@example.com"  # normalized/lowercased
        assert created["source"] == "manual"

        # GET one
        one = await client.get(f"/api/v1/contacts/{created['id']}")
        assert one.status_code == 200

        # LIST
        listing = await client.get("/api/v1/contacts")
        assert listing.status_code == 200
        body = listing.json()
        assert body["total"] >= 1
        assert any(c["id"] == created["id"] for c in body["items"])

    async def test_email_is_unique(self, client):
        await client.post("/api/v1/contacts", json={"email": "dup@example.com"})
        resp = await client.post("/api/v1/contacts", json={"email": "DUP@example.com"})
        assert resp.status_code == 409

    async def test_search(self, client):
        await client.post(
            "/api/v1/contacts", json={"name": "Grace Hopper", "email": "grace@navy.mil"}
        )
        resp = await client.get("/api/v1/contacts?search=grace")
        assert resp.status_code == 200
        assert any(c["name"] == "Grace Hopper" for c in resp.json()["items"])

    async def test_update_and_soft_delete(self, client):
        c = (await client.post("/api/v1/contacts", json={"email": "u@example.com"})).json()
        upd = await client.patch(f"/api/v1/contacts/{c['id']}", json={"name": "Updated"})
        assert upd.status_code == 200
        assert upd.json()["name"] == "Updated"

        dele = await client.delete(f"/api/v1/contacts/{c['id']}")
        assert dele.status_code == 204
        # Hidden from listing
        listing = await client.get("/api/v1/contacts?search=u@example.com")
        assert not any(item["id"] == c["id"] for item in listing.json()["items"])

        # Restore
        restored = await client.post(f"/api/v1/contacts/{c['id']}/restore")
        assert restored.status_code == 200
        assert restored.json()["is_deleted"] is False


class TestContactsVcard:
    def test_parse_basic_card(self):
        text = (
            "BEGIN:VCARD\nVERSION:3.0\n"
            "FN:Ada Lovelace\nN:Lovelace;Ada;;;\n"
            "EMAIL;TYPE=internet:ada@example.com\n"
            "TEL;TYPE=cell:+15551234\nORG:Analytical Inc.\n"
            "END:VCARD\n"
        )
        cards = parse_vcard(text)
        assert len(cards) == 1
        assert cards[0]["name"] == "Ada Lovelace"
        assert cards[0]["emails"] == ["ada@example.com"]
        assert cards[0]["phones"] == ["+15551234"]
        assert cards[0]["company"] == "Analytical Inc."

    def test_round_trip_serialize(self):
        class _C:
            name = "Ada Lovelace"
            email = "ada@example.com"
            emails_extra = ["ada@work.com"]
            phone = "+15551234"
            phone_secondary = None
            company = "Analytical Inc."
            title = None
            notes = "Line1\nLine2"

        text = serialize_vcard(_C())
        assert "BEGIN:VCARD" in text
        assert "EMAIL;TYPE=internet:ada@example.com" in text
        assert "EMAIL;TYPE=internet:ada@work.com" in text
        # Round-trip back through the parser
        parsed = parse_vcard(text)[0]
        assert parsed["name"] == "Ada Lovelace"
        assert "ada@example.com" in parsed["emails"]

    async def test_export_then_import(self, client):
        await client.post(
            "/api/v1/contacts", json={"name": "Export Me", "email": "exp@example.com"}
        )
        exported = await client.get("/api/v1/contacts/export")
        assert exported.status_code == 200
        assert exported.headers["content-type"].startswith("text/vcard")
        assert "BEGIN:VCARD" in exported.text

        # Import into a fresh-ish dataset (dedup by email → 0 new since it exists)
        before = (await client.get("/api/v1/contacts")).json()["total"]
        imported = await client.post(
            "/api/v1/contacts/import",
            files={"file": ("contacts.vcf", exported.text.encode(), "text/vcard")},
        )
        assert imported.status_code == 200
        assert imported.json()["imported"] == 0  # already present
        after = (await client.get("/api/v1/contacts")).json()["total"]
        assert after == before
