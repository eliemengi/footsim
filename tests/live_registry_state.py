"""
Der autorisierte Zustand der echten, lokalen Registry - an EINER Stelle.

WARUM ES DIESE DATEI GIBT
-------------------------
Bis C21 hielten fuenf Testdateien je fuer sich fest, dass die echte
Registry noch im Zustand von C20 steht: aktives Modell
`clm-3475c9aacef6fec9-lsa165be9c`, Fingerabdruck `66345556...`. Das war
richtig, solange jede Aktivierung verboten war, und es war genau die
Aussage, die diese Bloecke treffen sollten: "nichts wurde aktiviert".

Mit V2-C22 ist die lokale Aktivierung des C20-Kandidaten ausdruecklich
freigegeben. Danach waeren diese fuenf Aussagen falsch, obwohl nichts
schiefging. Statt sie einzeln aufzuweichen, steht der jeweils
autorisierte Zustand hier, exakt gepinnt. Die Tests pruefen weiterhin
zweierlei: dass sie selbst die Registry nicht veraendern (vorher gleich
nachher) und dass die Registry genau im autorisierten Zustand steht.

Aendert sich dieser Zustand durch eine weitere, ausdrueckliche Freigabe,
wird er hier nachgetragen - mit dem Block, der ihn autorisiert hat.
"""

#: Der Stand bis einschliesslich V2-C21.
PRE_C22_ACTIVE_ID = "clm-3475c9aacef6fec9-lsa165be9c"
PRE_C22_REGISTRY_FP = (
    "66345556ea317311fe3681700a2d4bf55d6f71a2fa303624145efe431a4f132a")
PRE_C22_ACTIVE_TEAMS = 63

#: Der C20-Kandidat, freigegeben durch C20 (Match) und C21 (Saison).
CANDIDATE_ID = "clm-936ecce472696ccb-ls1c4f4e1d"
CANDIDATE_TEAMS = 146

#: Der JETZT autorisierte Zustand: lokale Aktivierung in V2-C22 ueber
#: `run_ml.py --release-c16 apply --expect-model-id ...`, ausdruecklich
#: freigegeben. Vorher aktiv war PRE_C22_ACTIVE_ID; es steht jetzt als
#: Rueckfallziel in der Registry, der gesicherte Vorzustand traegt
#: PRE_C22_REGISTRY_FP.
AUTHORIZED_BY = "V2-C22 (lokale Aktivierung, ausdruecklich freigegeben)"
ACTIVE_ID = CANDIDATE_ID
REGISTRY_FP = (
    "f79bc8566c18dfaa93e36f24df7432537f864b983e099f0d4c3dbfa2810b4b33")
ACTIVE_TEAMS = CANDIDATE_TEAMS
