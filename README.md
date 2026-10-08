# pihole-blocklist

En egen, kurerad blocklista för Pi-hole. Tjänsten hämtar ett urval uppströmslistor
(utgångspunkt: [Firebogs](https://firebog.net/) "ticked"-listor), normaliserar och
deduplicerar dem, tar bort allowlistade domäner och serverar allt som **en enda URL**.

Pi-hole behöver då bara känna till en adlist, och vilka källor som ingår styrs från det här repot.

## Struktur

| Fil | Syfte |
|---|---|
| `lists/sources.txt` | Uppströmslistor (en URL per rad) |
| `lists/allowlist.txt` | Domäner som aldrig ska blockeras |
| `lists/blocklist.txt` | Egna domäner som alltid ska blockeras |
| `blocklist.py` | Hämtar, slår ihop och serverar (bara Python stdlib) |

Parsern klarar hosts-format (`0.0.0.0 example.com`), rena domänlistor och enkla
adblock-regler (`||example.com^`). Ogiltiga rader, IP-adresser och `localhost` filtreras bort.

Om en källa inte går att hämta används senast lyckade kopian (`output/cache/`). Om
*alla* källor fallerar behålls den tidigare sammanslagna listan.

## Köra med Docker (rekommenderat)

```sh
docker compose up -d --build
```

Endpoints:

- `http://<host>:8080/blocklist.txt` – den sammanslagna listan
- `http://<host>:8080/stats.json` – antal domäner per källa, status, tidpunkt
- `http://<host>:8080/health` – healthcheck

Listan byggs vid start och sedan var `REFRESH_HOURS`:e timme (default 12).
Eftersom `lists/` monteras in räcker det att `git pull` på servern – ändringarna
slår igenom vid nästa ombygge (eller direkt med `docker compose restart`).

## Köra utan Docker

```sh
python3 blocklist.py build                  # bygg output/blocklist.txt en gång
python3 blocklist.py serve --port 8080      # bygg + servera + bygg om periodiskt
```

## Peka Pi-hole mot tjänsten

1. Pi-hole admin → **Lists** (Adlists) → lägg till `http://<host>:8080/blocklist.txt`
2. Ta gärna bort de enskilda Firebog-listorna du hade innan, de ingår nu här.
3. Uppdatera gravity: `pihole -g` (eller *Tools → Update Gravity*).

Pi-hole uppdaterar gravity själv en gång i veckan; vill du ha tätare uppdateringar,
lägg till ett cronjobb på Pi-hole-maskinen, t.ex. `0 4 * * * pihole -g`.

## Underhåll

- **Lägga till/ta bort en källa:** redigera `lists/sources.txt`, committa.
- **Något legitimt blockeras:** lägg domänen i `lists/allowlist.txt`.
- **Kolla vilken källa som bidrar mest / har slutat fungera:** `stats.json`.
