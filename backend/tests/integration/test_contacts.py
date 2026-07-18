"""Integration tests for the contacts module (CRUD, rich fields, groups, vCard)."""

from app.models.email_account import EmailAccount
from app.models.email_folder import EmailFolder
from app.models.email_message import EmailMessage
from app.services.contact_service import parse_vcard, serialize_vcard


class TestContactsBulkDelete:
    async def test_bulk_delete_soft_deletes_and_is_idempotent(self, client):
        a = (await client.post("/api/v1/contacts", json={"email": "a@x.com"})).json()
        b = (await client.post("/api/v1/contacts", json={"email": "b@x.com"})).json()
        c = (await client.post("/api/v1/contacts", json={"email": "c@x.com"})).json()

        # a + b + a non-existent id → idempotent (no 404), single update.
        resp = await client.post("/api/v1/contacts/bulk-delete", json=[a["id"], b["id"], 999999])
        assert resp.status_code == 204

        ids = {item["id"] for item in (await client.get("/api/v1/contacts")).json()["items"]}
        assert a["id"] not in ids
        assert b["id"] not in ids
        assert c["id"] in ids  # untouched

        # Re-post with an already-deleted id — still 204, no partial-commit error.
        resp2 = await client.post("/api/v1/contacts/bulk-delete", json=[b["id"], c["id"]])
        assert resp2.status_code == 204
        ids2 = {item["id"] for item in (await client.get("/api/v1/contacts")).json()["items"]}
        assert c["id"] not in ids2

    async def test_bulk_delete_empty_list(self, client):
        resp = await client.post("/api/v1/contacts/bulk-delete", json=[])
        assert resp.status_code == 204

    async def test_bulk_deleted_contacts_restorable(self, client):
        a = (await client.post("/api/v1/contacts", json={"email": "r@x.com"})).json()
        await client.post("/api/v1/contacts/bulk-delete", json=[a["id"]])
        restored = await client.post(f"/api/v1/contacts/{a['id']}/restore")
        assert restored.status_code == 200
        assert restored.json()["is_deleted"] is False


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
        assert created["is_favorite"] is False
        assert created["groups"] == []

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


class TestContactsRichFields:
    async def test_rich_create_round_trip(self, client):
        payload = {
            "name": "Ada Lovelace",
            "email": "ada@analytical.com",
            "nickname": "Ada",
            "company": "Analytical Inc.",
            "department": "Mathematics",
            "profession": "Mathematician",
            "phones": [
                {"type": "mobile", "value": "+15551000"},
                {"type": "work", "value": "+15552000"},
            ],
            "addresses": [
                {
                    "type": "work",
                    "street": "1 Computing Lane",
                    "city": "London",
                    "region": "ENG",
                    "postal_code": "W1",
                    "country": "UK",
                }
            ],
            "websites": ["https://ada.example.com"],
            "dates": [{"type": "birthday", "label": None, "date": "1815-12-10"}],
            "im_handles": [{"type": "skype", "value": "ada.lovelace"}],
            "relationships": [{"type": "spouse", "value": "William King"}],
            "notes": "First programmer.",
        }
        created = (await client.post("/api/v1/contacts", json=payload)).json()
        cid = created["id"]
        # Primary phone mirrored to legacy column for search.
        assert created["phone"] == "+15551000"
        assert created["phone_secondary"] == "+15552000"
        assert created["phones"] == payload["phones"]
        assert created["addresses"] == payload["addresses"]
        assert created["nickname"] == "Ada"
        assert created["department"] == "Mathematics"

        # GET round-trips every structured field.
        got = (await client.get(f"/api/v1/contacts/{cid}")).json()
        for key in (
            "phones",
            "addresses",
            "websites",
            "dates",
            "im_handles",
            "relationships",
        ):
            assert got[key] == payload[key], key

        # Mirrored phone is searchable.
        srch = await client.get("/api/v1/contacts?search=15551000")
        assert any(item["id"] == cid for item in srch.json()["items"])

    async def test_favorite_toggle_and_filter(self, client):
        c = (await client.post("/api/v1/contacts", json={"email": "fav@example.com"})).json()
        fav = await client.patch(f"/api/v1/contacts/{c['id']}", json={"is_favorite": True})
        assert fav.json()["is_favorite"] is True
        only = await client.get("/api/v1/contacts?favorites_only=true")
        assert any(item["id"] == c["id"] for item in only.json()["items"])

    async def test_legacy_phone_row_hydrates_phones(self, client):
        """A row created with only the legacy ``phone`` column still renders a phones list."""
        c = (
            await client.post(
                "/api/v1/contacts",
                json={"email": "leg@example.com", "phone": "+1999"},
            )
        ).json()
        # Service mirrored phone[0] into phones; assert hydration returns a list.
        got = (await client.get(f"/api/v1/contacts/{c['id']}")).json()
        assert got["phones"] is not None
        assert got["phones"][0]["value"] == "+1999"

    async def test_list_legacy_phone_row_does_not_break(self, client):
        """LIST (list_all + count + model_validate) over a legacy phone row.

        Regression: hydrating phones by mutating the ORM object marked the row
        dirty; the list ``count`` query then autoflushed it, firing
        ``updated_at``'s onupdate and invalidating the column, so the sync
        ``model_validate`` raised MissingGreenlet → 500. Reads must not mutate.
        """
        c = (
            await client.post(
                "/api/v1/contacts",
                json={"email": "leg2@example.com", "phone": "+1-555-legacy"},
            )
        ).json()
        listing = await client.get("/api/v1/contacts?search=leg2")
        assert listing.status_code == 200
        item = next(i for i in listing.json()["items"] if i["id"] == c["id"])
        assert item["phones"] is not None
        assert item["phones"][0]["value"] == "+1-555-legacy"
        assert item["updated_at"]  # not invalidated/blanked


class TestContactGroups:
    async def test_group_crud_and_membership(self, client):
        g = (
            await client.post("/api/v1/contacts/groups", json={"name": "Work", "color": "#3b82f6"})
        ).json()
        assert g["name"] == "Work"
        assert g["member_count"] == 0

        # Duplicate name → 409
        dup = await client.post("/api/v1/contacts/groups", json={"name": "Work"})
        assert dup.status_code == 409

        # Assign a contact to the group via create.
        c = (
            await client.post(
                "/api/v1/contacts",
                json={"email": "g@example.com", "group_ids": [g["id"]]},
            )
        ).json()
        assert any(grp["id"] == g["id"] for grp in c["groups"])

        # Member count reflects; list filters by group.
        groups = (await client.get("/api/v1/contacts/groups")).json()
        assert next(x for x in groups if x["id"] == g["id"])["member_count"] == 1
        filtered = await client.get(f"/api/v1/contacts?group_id={g['id']}")
        assert any(item["id"] == c["id"] for item in filtered.json()["items"])

        # Clear membership with an empty list.
        cleared = await client.patch(f"/api/v1/contacts/{c['id']}", json={"group_ids": []})
        assert cleared.json()["groups"] == []

        # Rename + delete.
        renamed = await client.patch(
            f"/api/v1/contacts/groups/{g['id']}", json={"name": "Colleagues"}
        )
        assert renamed.json()["name"] == "Colleagues"
        dele = await client.delete(f"/api/v1/contacts/groups/{g['id']}")
        assert dele.status_code == 204

    async def test_unknown_group_id_ignored(self, client):
        c = (
            await client.post(
                "/api/v1/contacts",
                json={"email": "k@example.com", "group_ids": [999999]},
            )
        ).json()
        assert c["groups"] == []


class TestRelatedEmails:
    async def test_related_emails_match(self, client, db_session):
        # Seed an email account + folder + two messages (one matching the contact).
        acct = EmailAccount(
            label="a",
            email_address="me@example.com",
            imap_host="127.0.0.1",
            imap_port=993,
            smtp_host="127.0.0.1",
            smtp_port=465,
            username="me",
            password_encrypted="x",
        )
        db_session.add(acct)
        await db_session.flush()
        folder = EmailFolder(account_id=acct.id, folder_name="INBOX", uidvalidity=1)
        db_session.add(folder)
        await db_session.flush()
        db_session.add_all(
            [
                EmailMessage(
                    account_id=acct.id,
                    folder_id=folder.id,
                    uid=1,
                    from_address="pal@friends.com",
                    to_addresses=[{"address": "me@example.com", "name": None}],
                    subject="Hello",
                    sent_at=None,
                ),
                EmailMessage(
                    account_id=acct.id,
                    folder_id=folder.id,
                    uid=2,
                    from_address="me@example.com",
                    to_addresses=[{"address": "other@elsewhere.com", "name": None}],
                    subject="Sent by me",
                    sent_at=None,
                ),
            ]
        )
        await db_session.commit()

        c = (
            await client.post("/api/v1/contacts", json={"email": "me@example.com", "name": "Me"})
        ).json()
        emails = (await client.get(f"/api/v1/contacts/{c['id']}/emails")).json()
        assert len(emails) == 2
        assert {e["subject"] for e in emails} == {"Hello", "Sent by me"}


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
        assert cards[0]["phones_typed"] == [{"type": "mobile", "value": "+15551234"}]
        assert cards[0]["company"] == "Analytical Inc."

    def test_parse_rich_fields(self):
        text = (
            "BEGIN:VCARD\nVERSION:3.0\nFN:Bo\n"
            "NICKNAME:B\n"
            "EMAIL;TYPE=internet:bo@example.com\n"
            "ADR;TYPE=home:;;2 St;Town;CA;90210;US\n"
            "URL:https://bo.example.com\n"
            "BDAY:1990-05-05\n"
            "CATEGORIES:Friends,VIP\n"
            "END:VCARD\n"
        )
        card = parse_vcard(text)[0]
        assert card["addresses"][0]["city"] == "Town"
        assert card["addresses"][0]["postal_code"] == "90210"
        assert card["websites"] == ["https://bo.example.com"]
        assert card["dates"] == [{"type": "birthday", "label": None, "date": "1990-05-05"}]
        assert card["categories"] == ["Friends", "VIP"]
        assert card["nickname"] == "B"

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

    def test_serialize_rich_contact(self):
        class _G:
            def __init__(self, name):
                self.name = name

        class _C:
            name = "Ada Lovelace"
            email = "ada@example.com"
            emails_extra = None
            phone = None
            phone_secondary = None
            company = "Analytical Inc."
            title = None
            notes = None
            nickname = "Ada"
            phones = [{"type": "mobile", "value": "+1555"}]
            addresses = [
                {
                    "type": "home",
                    "street": "2 St",
                    "city": "Town",
                    "region": "CA",
                    "postal_code": "90210",
                    "country": "US",
                }
            ]
            websites = ["https://ada.example.com"]
            dates = [{"type": "birthday", "label": None, "date": "1815-12-10"}]
            im_handles = [{"type": "skype", "value": "ada"}]
            groups = [_G("Friends")]

        text = serialize_vcard(_C())
        assert "TEL;TYPE=cell:+1555" in text
        assert "ADR;TYPE=home;;2 St;Town;CA;90210;US" in text
        assert "URL:https://ada.example.com" in text
        assert "BDAY:1815-12-10" in text
        assert "NICKNAME:Ada" in text
        assert "CATEGORIES:Friends" in text

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
