# Room server (signaling) – deploy guide

The browser version needs this small server so players can find each other with
**room codes**. It only passes the connection set-up messages; the game itself
runs between the players' browsers. No game data, no accounts, no database.

* File: `signaling_server.py` (Python 3, standard library only, nothing to install)
* Local test: `python signaling_server.py` → `ws://localhost:9080`

## Put it online for free (Render, ~10 minutes)

1. Create a free GitHub account (if you have none) and a new **public or private
   repository**, e.g. `ccs-room-server`. Upload `signaling_server.py` into it
   (GitHub → *Add file → Upload files*).
2. Create a free account at **render.com** (sign in with GitHub).
3. *New → Web Service* → pick the repository.
4. Settings:
   * Language / Runtime: **Python 3**
   * Build command: leave empty (or `echo ok`)
   * Start command: `python signaling_server.py`
   * Instance type: **Free**
5. *Create Web Service*. After the build Render shows an address like
   `https://ccs-room-server.onrender.com`.
6. Open that address in the browser: it should say
   "Cardboard Clinic Simulator signaling server is running."
7. Send me the address. The game then uses `wss://ccs-room-server.onrender.com`
   (in `game/scripts/core/build_info.gd`, `SIGNALING_URL`) and I export the web
   build again.

**Free plan note:** Render puts free services to sleep after ~15 minutes without
visitors. The first "Create room" after a pause can take up to a minute; the game
waits 15 s and then asks to try again. A paid plan (~7 $/month) or another host
(Fly.io, Railway, a small VPS) avoids that.

## Limits

* Up to 4 players per room, private codes only, rooms close when the host leaves.
* Only free public STUN servers are used. Players behind very strict company or
  university networks may not be able to connect (a TURN relay would fix that later).
