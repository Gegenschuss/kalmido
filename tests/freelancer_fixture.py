"""2.87.9 (#1919) the test fixture "Selbstständige": a person WITHOUT any organisation on a server that has organisations
(a freelancer: the own private space, the own personal office, its own admin there). For every suite that checks a route
for freelancer parity (tests/freelancer_coverage_test.py, marker "freelancer-matrix: <area>"):

    from freelancer_fixture import freelancer
    FID, Fr = freelancer(B, A)                  # A = a logged-in instance admin's session, B = the server's base URL
    FID, Fr = freelancer(B, A, "fiona")         # a second one (another name)

The person is created by the admin without "orgs", logs in with a fresh session (the X-Requested-With header set), has
English, the tour done and every module on (FEATURES), so that no area is hidden by a switch."""
import requests

H = {"X-Requested-With": "kalmido"}
PASSWORD = "password123"
# the default modules plus the ones a purpose / an admin switches on (family, Home & life, office, clients, the hub)
FEATURES = ("cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,comments,events,contacts,files,docs,"
            "family,contracts,home,care,health,review,travel,reading,clients,office,dispo,workload,forms,wiki,budget,feeds")


def login(base, user, pw=PASSWORD):
    s = requests.Session()
    s.headers.update(H)
    r = s.post(base + "/api/auth/login", json={"username": user, "password": pw})
    assert r.ok, (user, r.text)
    return s


def freelancer(base, admin, name="frida", features=FEATURES):
    """-> (user id, logged-in session) of a new person without an organisation."""
    r = admin.post(base + "/api/users", json={"username": name, "display_name": name.title(), "password": PASSWORD,
                                              "email": f"{name}@example.com", "orgs": []})
    assert r.ok, r.text
    uid = r.json()["id"]
    s = login(base, name)
    r = s.patch(base + "/api/settings", json={"lang": "en", "features": features, "tour": "done"})
    assert r.ok, r.text
    ws = s.get(base + "/api/state").json()["me"].get("workspaces") or []
    assert ws == [], f"the freelancer {name} must not be in an organisation: {ws}"
    return uid, s


def org_join(base, user, oid, pw=PASSWORD):
    """2.148.1 (#2480): an existing account an organisation admin added by e-mail / id is only invited: the person accepts
    (POST /api/orgs/<oid>/join). True once they are a member (also when an instance admin added them directly)."""
    s = login(base, user, pw)
    if s.post(base + f"/api/orgs/{oid}/join").ok:
        return True
    return any(o["id"] == oid for o in s.get(base + "/api/orgs").json().get("orgs", []))
