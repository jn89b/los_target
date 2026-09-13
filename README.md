# LOS Target Waypoint Planner

Streamlit app that computes a delayed-engagement intercept waypoint for a UAS
(loitering or on a straight track) against a moving target, from
latitude/longitude or 8-digit MGRS grid input.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Run

```bash
uv run los-target
```

or equivalently:

```bash
uv run streamlit run src/los_target/app.py
```

This opens the app in your browser (default: http://localhost:8501).

## Using the app

The app is organized into 5 sections, in the order you fill them out.

### 1. Target location

| Parameter | Accounts for |
| --- | --- |
| Target ID | Groups position reports so history/estimation only use entries for the same target. Use the same ID every time you re-report the same target. |
| Target location | The target's position at the entry time, as decimal degrees (`11.3283, 146.2276`) or an 8-digit MGRS grid (`55PDN15715239`, 4-digit easting + 4-digit northing, ~10 m precision). |
| Entry date / Entry time | The timestamp this position was observed/reported. Used to order history and to compute elapsed time between reports for bearing/speed estimation — it is not "now", so back-dated reports are supported. |

Saving an entry appends it to `data/target_history.csv` and is required before
you can compute a waypoint (the most recent saved entry becomes the target's
current position).

### 2. Target motion

| Parameter | Accounts for |
| --- | --- |
| Target bearing/speed source | Whether to derive motion from two or more saved history entries, or to type it in directly (e.g. from a separate report or estimate). |
| Target speed (m/s) | The target's constant ground speed used to project its future position during the engagement delay and after. |
| Target bearing (deg, from true north) | The target's constant ground track direction (0 = north, 90 = east, ...), used with speed to project its straight-line path. |

When estimating from history, the earliest and latest saved entries for the
target ID are used: displacement between them divided by elapsed time gives
speed, and the bearing between them gives track direction. The number inputs
are pre-filled with the estimate but remain editable so you can override them.

### 3. Ownship / UAS

| Parameter | Accounts for |
| --- | --- |
| UAS delay mode | Whether the UAS is circling a fixed point (`LOITER`) or flying a straight track (`STRAIGHT`) while it waits out the engagement delay — this changes where the UAS ends up when the engagement command finally takes effect. |
| UAS airspeed (m/s) | The UAS's constant ground speed, both during the delay and for the post-delay intercept leg. Determines how far it can travel and, in loiter mode, its angular turn rate (`speed / radius`). |
| Loiter center location | The lat/lon (decimal or MGRS) the UAS orbits around in `LOITER` mode. |
| Loiter radius (m) | The radius of that orbit; combined with airspeed it sets the loiter period and turn rate. |
| Turn direction (CW/CCW) | Which way the UAS orbits the loiter center, which determines its tangential ground track at any point on the circle. |
| UAS current position (RADIAL_BEARING_FROM_CENTER vs UAS_INITIAL_LAT_LON) | How you specify where on the loiter circle the UAS currently is: either a bearing from the center (e.g. 0° = due north of center), or the UAS's own coordinate (validated to lie within tolerance of the configured radius). |
| Radial bearing from loiter center to UAS (deg) | Used only in `RADIAL_BEARING_FROM_CENTER` mode — the compass bearing from the loiter center to the UAS's current point on the circle. |
| UAS current location | Used in `STRAIGHT` mode (or `UAS_INITIAL_LAT_LON` loiter mode) — the UAS's actual current lat/lon. |
| UAS bearing (deg, from true north) | Used only in `STRAIGHT` mode — the UAS's constant ground track while it waits out the delay. |

### 4. Timing

| Parameter | Accounts for |
| --- | --- |
| Engagement delay (s) | How long from now until the UAS can act on a new waypoint command (e.g. time since the last target report plus time to relay the command). Both the UAS and target are projected forward by this much before the intercept is solved. |
| Target report time (s from now) | A separate "requested time" used only for map/plot display — where the target is predicted to be at this time from now, independent of the engagement delay. |
| Generate map after computing | Whether to render the interactive Folium map (loiter orbit, delay paths, projected target track, computed waypoint) after computing. |

### 5. Compute waypoint

Builds the local planning frame, advances the UAS and target through the
engagement delay, and solves for the earliest point after the delay where the
UAS (at its fixed airspeed, free to choose any heading) can reach the target's
projected straight-line track. Results shown:

| Output | Accounts for |
| --- | --- |
| Waypoint latitude/longitude/MGRS | Where to send the UAS so its post-delay track intersects the target's projected track. |
| Time after engagement | Additional flight time needed after the delay ends to reach the waypoint. |
| Total time from now | Engagement delay + time after engagement — the full time from now until intercept. |
| Post-delay route distance | Straight-line distance the UAS flies after the delay to reach the waypoint, at its configured airspeed. |
| Command bearing from engagement point | The heading to give the UAS at the moment the delay ends. |

If no waypoint is reachable (e.g. UAS airspeed too low relative to target
speed/geometry), the app reports that no solution was found instead of a
result. Every computed solution is appended to `data/solutions.json` for an
audit trail of inputs and outputs.

## How the algorithm works

**1. Local planning frame.** All lat/lon inputs are averaged to a regional
origin, and an azimuthal-equidistant (`aeqd`) projection is built around it
(`geometry.LocalFrame`). This turns geographic coordinates into a flat
North/East meter frame so the motion and intercept math is ordinary vector
algebra instead of spherical trigonometry — accurate for regional-scale
distances (tens of km), not for entire continents.

**2. Motion models.** The target is always a straight track: constant speed
along a fixed bearing. Its position at time $t$ is:

$$
\mathbf{p}_{\text{target}}(t) = \mathbf{p}_0 + \mathbf{v}\,t, \qquad
\mathbf{v} = v_{\text{target}} \begin{bmatrix} \cos\theta \\ \sin\theta \end{bmatrix}
$$

where $\mathbf{p}_0$ is its last known North/East position, $v_{\text{target}}$
its speed, and $\theta$ its bearing from true north. The UAS is either the
same straight-track model, or a circular loiter around a center
$\mathbf{c}$ with radius $R$ at speed $v_{\text{uas}}$:

$$
\omega = \pm \frac{v_{\text{uas}}}{R}, \qquad
\mathbf{p}_{\text{uas}}(t) = \mathbf{c} + R \begin{bmatrix} \cos(\phi_0 + \omega t) \\ \sin(\phi_0 + \omega t) \end{bmatrix}
$$

where $\phi_0$ is the UAS's initial phase angle on the circle and the sign of
$\omega$ is set by the turn direction (CW/CCW).

**3. Propagate through the engagement delay.** Both the target and the UAS
are advanced from "now" to $t = \tau$ (the engagement delay) using the
models above: $\mathbf{p}_{\text{target}}(\tau)$ and $\mathbf{p}_{\text{uas}}(\tau)$.
This gives their predicted positions at the moment the UAS can actually act on
a new command — everything before that is assumed fixed/already in motion and
not re-plannable.

**4. Solve the fixed-speed pursuit intercept.** From the delay-end state, the
UAS is assumed free to turn to any heading but must fly at its fixed airspeed
$v_{\text{uas}}$. Let

$$
\mathbf{r} = \mathbf{p}_{\text{target}}(\tau) - \mathbf{p}_{\text{uas}}(\tau)
$$

be the target's position relative to the UAS at delay-end, and $\mathbf{v}$ be
the target's (constant) velocity vector. The target's future position at time
$t$ after the delay is $\mathbf{r} + \mathbf{v}t$; the UAS can reach a point at
distance $v_{\text{uas}}\,t$ in that same time. Setting
$\lVert \mathbf{r} + \mathbf{v}t \rVert = v_{\text{uas}}\,t$ and squaring gives
a quadratic in $t$:

$$
a\,t^2 + b\,t + c = 0
$$

$$
a = \mathbf{v}\cdot\mathbf{v} - v_{\text{uas}}^2, \qquad
b = 2\,(\mathbf{r}\cdot\mathbf{v}), \qquad
c = \mathbf{r}\cdot\mathbf{r}
$$

$$
t = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}
$$

The smallest positive root $t$ is the earliest feasible intercept time; the
waypoint is $\mathbf{r} + \mathbf{v}t$ evaluated from the target's delay-end
position, i.e. $\mathbf{p}_{\text{target}}(\tau) + \mathbf{v}t$. If the
discriminant $b^2 - 4ac$ is negative (the target's speed advantage makes it
unreachable at any heading) or no positive root exists, the app reports no
solution.

**5. Report results.** The intercept time is converted back to a heading
command $\big(\text{bearing from } \mathbf{p}_{\text{uas}}(\tau) \text{ to the waypoint}\big)$
and the waypoint's local North/East coordinates are converted back to
lat/lon/MGRS through the same local frame.

**Model assumptions / limitations:** target and UAS both fly straight,
constant-speed legs after the delay (no turn-rate or turn-radius limits on the
UAS's post-delay leg); no wind, terrain, geofences, or collision avoidance;
the target's course/speed are assumed to hold from the last report through the
entire delay and intercept — stale or manually-entered target motion will
directly bias the computed waypoint.

## Data files

Cached data lives under `data/` in the repo root (created automatically):
- `target_history.csv` — saved target position reports
- `solutions.json` — computed waypoint solutions
