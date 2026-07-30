# Design plan

Written before any component, per the brief. This records the palette, type,
signature element, and, at the end, what was revised away from a default.

## The subject decides the design

incident-desk is opened at 3am, by a stressed on-call engineer, often on a
phone, sometimes colour-blind, always in a hurry. Every decision below is
justified against that reader, not against what looks good in a portfolio
screenshot.

Concrete consequences the brief calls out, and how this design answers them:

- **Severity is never colour alone.** Every severity carries a shape/label
  token (a filled square glyph plus the `SEV1`..`SEV4` text and a distinct
  left-border weight), so it survives greyscale, colour-blindness, and a
  dimmed 3am screen. Colour reinforces; it never carries the signal by itself.
- **The timeline is the spine, not a side panel.** On the incident detail
  page the append-only timeline runs down the centre column as the primary
  content; metadata (status, assignee, severity) sits in a header rail above
  it and a thin context rail beside it. Everything is arranged around the
  timeline.
- **Density over whitespace.** This is an operations console. Rows are compact
  (36px), the type scale is tight, and the incident list shows many rows
  without scrolling. Generous whitespace would mean less situational awareness.
- **Destructive actions have friction.** Resolve, delete, revoke, and remove
  use a confirm step and a distinct treatment; they are never one careless tap
  away.

## Palette: "Signal on Slate"

Five named colours. The base is a cool desaturated slate (not near-black, not
grey-blue dashboard default): easy on the eyes in a dark room, high enough
contrast for AA text, and neutral enough that severity colours pop against it.

| Name | Hex | Role |
|---|---|---|
| Slate | `#161a22` | App background (dark); the calm base everything sits on |
| Paper | `#f4f6f9` | App background (light) |
| Ink | `#e7ebf2` (dark) / `#1b2230` (light) | Primary text |
| Amber | `#f2a63b` | Primary accent: focus rings, active nav, primary buttons. A warm signal-amber, the colour of a caution light, not the acid-green cliché |
| Pulse | `#3d8bff` | Secondary accent: links, live/real-time indicators, the presence dot |

Severity ramp (used with a glyph and label, never alone), tuned so each hue is
distinguishable under the common deuteranopia/protanopia confusions:

| Severity | Hex | Reinforced by |
|---|---|---|
| SEV1 | `#f0476b` (rose) | filled square + heaviest left border + `SEV1` |
| SEV2 | `#f2a63b` (amber) | filled square + heavy border + `SEV2` |
| SEV3 | `#3d8bff` (blue) | outline square + medium border + `SEV3` |
| SEV4 | `#7d8798` (grey) | outline square + thin border + `SEV4` |

Status colours are deliberately calmer (open/acknowledged/mitigated/resolved/
postmortem) so severity stays the loudest thing on screen.

## Type

Two faces, both self-hosted (no default system stack, and not the
serif-display pairing every AI mock reaches for):

- **Display / headings: Space Grotesk.** A characterful geometric grotesque
  with just enough personality (the distinctive `a`, `g`) to give the product
  an identity, used with restraint: page titles, the wordmark, section
  headers, incident numbers (`INC-217`). Not used for body.
- **Body / UI / data: Inter.** The workhorse. Legible at small sizes and high
  density, excellent number rendering, wide language coverage. Everything that
  isn't a heading.
- **Monospace: JetBrains Mono**, for request ids, tokens, and code-shaped
  payloads in the timeline.

Type scale (1.2 minor-third, tightened for density):

| Token | px / line-height | Use |
|---|---|---|
| `display` | 28 / 34 | page title |
| `h1` | 22 / 28 | section |
| `h2` | 18 / 24 | card header |
| `body` | 14 / 20 | default |
| `small` | 12.5 / 18 | metadata, table cells |
| `micro` | 11 / 15 | timestamps, labels |

## Signature element: the incident timeline

The product is remembered by its **timeline spine**: a vertical rail down the
centre of the incident detail page where every event (created, acknowledged,
severity changed, assigned, commented, escalated, attachment added, resolved)
is a node on a continuous line. Nodes are typed by a small glyph and colour;
system events (escalation, automation) are visually distinct from human
actions; the newest event is anchored at the bottom where the composer sits,
so reading top-to-bottom is reading the incident's history in order. It is the
first thing built and the thing every other screen is arranged to support.

## Motion and accessibility

- `prefers-reduced-motion`: all non-essential transition/animation is removed;
  the timeline still updates, just without the slide-in.
- Visible focus rings everywhere (2px Amber outline, offset), never removed.
- WCAG AA contrast on all text/background pairs, verified in both themes.
- Full keyboard operation; the incident list has `j`/`k`/`Enter`/`/` bindings.

## What was revised away from a default

Checking the first draft against the brief's list of clichés, three defaults
were caught and changed:

1. **Near-black + single acid-green accent** was the initial instinct (it's
   the current "ops tool" default). Rejected: it's explicitly named as a
   cliché, and acid green fails as a severity/status colour because it collides
   with "healthy/resolved" semantics. Replaced with the slate base + warm
   signal-amber primary, which reads as *caution console* rather than *hacker
   terminal*.
2. **A high-contrast serif display face** (the cream-and-terracotta editorial
   look) was considered for headings. Rejected as another named cliché and
   wrong for the subject: a 3am ops tool should not feel like a magazine.
   Space Grotesk keeps character without the editorial connotation.
3. **Severity encoded by colour chips alone** was the first list design.
   Revised the moment it was checked against "severity must never be encoded by
   colour alone": every severity now carries a glyph, a border weight, and the
   text label, so the signal survives greyscale and colour-blindness.
