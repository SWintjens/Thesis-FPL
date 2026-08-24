import json
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials

MEMBERS_FILE = "members.json"
CREDENTIALS_FILE = "credentials.json"

SPREADSHEET_PREFIX = "SW Betting"

BET_HEADERS = [
    "Date",
    "Home team",
    "Away team",
    "Prediction",
    "Model odds",
    "Pinnacle odds",
    "Unit size",
    "Status",
    "Result"
]


def load_members():
    if not os.path.exists(MEMBERS_FILE):
        return {}

    with open(MEMBERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_members(members):
    with open(MEMBERS_FILE, "w", encoding="utf-8") as f:
        json.dump(members, f, indent=4, ensure_ascii=False)


def get_gspread_client():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    creds = ServiceAccountCredentials.from_json_keyfile_name(
        CREDENTIALS_FILE,
        scope
    )
    return gspread.authorize(creds)


def format_header(ws, range_name):
    ws.format(range_name, {
        "textFormat": {"bold": True},
        "horizontalAlignment": "CENTER"
    })


def setup_bets_sheet(ws):
    ws.clear()
    ws.update("A1:I1", [BET_HEADERS])
    format_header(ws, "A1:I1")
    ws.freeze(rows=1)
    ws.columns_auto_resize(1, 9)


def setup_dashboard_sheet(ws, member_name):
    ws.clear()

    ws.update("A1", [[f"{member_name} Dashboard"]])
    ws.update("A3:B10", [
        ["KPI", "Value"],
        ["Total bets", ""],
        ["Open bets", ""],
        ["Settled bets", ""],
        ["Win rate", ""],
        ["Total units", ""],
        ["P/L", ""],
        ["ROI", ""]
    ])

    ws.format("A1", {
        "textFormat": {
            "bold": True,
            "fontSize": 16
        }
    })

    ws.format("A3:B3", {
        "textFormat": {"bold": True},
        "horizontalAlignment": "CENTER"
    })

    ws.freeze(rows=3)
    ws.columns_auto_resize(1, 6)


def create_member_spreadsheet(client, member_name, member_email):
    title = f"{SPREADSHEET_PREFIX} - {member_name}"

    spreadsheet = client.create(title)

    bets_ws = spreadsheet.sheet1
    bets_ws.update_title("BETS")

    dashboard_ws = spreadsheet.add_worksheet(
        title="Dashboards",
        rows=100,
        cols=20
    )

    setup_bets_sheet(bets_ws)
    setup_dashboard_sheet(dashboard_ws, member_name)

    spreadsheet.share(member_email, perm_type="user", role="reader")

    return {
        "sheet_id": spreadsheet.id,
        "sheet_url": f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}"
    }


def create_sheets_for_all_members():
    members = load_members()

    if not members:
        print("Geen members gevonden in members.json")
        return

    client = get_gspread_client()

    created_count = 0
    skipped_count = 0

    for name, info in members.items():
        email = info.get("email")
        active = info.get("active", True)
        existing_sheet_id = info.get("sheet_id")

        if not active:
            print(f"{name} is niet actief, overgeslagen.")
            skipped_count += 1
            continue

        if not email:
            print(f"{name} heeft geen email, overgeslagen.")
            skipped_count += 1
            continue

        if existing_sheet_id:
            print(f"{name} heeft al een sheet, overgeslagen.")
            skipped_count += 1
            continue

        try:
            result = create_member_spreadsheet(client, name, email)

            members[name]["sheet_id"] = result["sheet_id"]
            members[name]["sheet_url"] = result["sheet_url"]

            save_members(members)

            created_count += 1
            print(f"Sheet aangemaakt voor {name}: {result['sheet_url']}")

        except Exception as e:
            print(f"Fout bij {name}: {e}")

    print("")
    print(f"Klaar. {created_count} sheet(s) aangemaakt, {skipped_count} overgeslagen.")


if __name__ == "__main__":
    create_sheets_for_all_members()