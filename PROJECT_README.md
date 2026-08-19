# PARALLAX — Gunshot Detection & Localization System

*A distributed, multi-sensor system that listens for gunfire, decides whether a
sound is actually a gunshot, and works out where it came from — direction,
and where possible, exact range.*

> **Status: software prototype.** No hardware has been built. No real gunshots
> were recorded. Every waveform in this project is a physics-based simulation,
> and every accuracy number quoted below comes from testing against that
> simulation, not from a field trial. This is stated plainly here because a
> simulated result presented as a real-world measurement is the fastest way to
> lose credibility with anyone technical reviewing this project.

---

## 1. The Problem We're Solving

This project is built around a real problem statement (from Smart India
Hackathon): **build a system that can detect a gunshot and tell you which
direction it came from, using an array of microphones.**

The idea behind it is simple and important. When a shot is fired at a
soldier or a patrol, the sound reaches human ears in under a second — but a
human being startled by a gunshot is not a reliable direction-finder. People
freeze, misjudge direction, or simply can't react fast enough. A
sensor-based system doesn't get startled. If several microphones can hear the
same sound arrive at very slightly different times, geometry alone can work
out where the sound came from — no guessing required.

But direction alone is only half the answer a commander actually needs. Two
questions matter in the moment right after a shot is fired:

1. **Which way do I look?** (direction)
2. **How far away is the danger?** (distance)

A basic microphone array can answer the first question well. Answering the
second question — *distance* — turns out to be a much harder problem, and
solving it properly, without cheating, is the core technical achievement of
this project.

---

## 2. What Makes This Hard (and What Makes It Interesting)

Most simple approaches try to guess distance from how *loud* the gunshot
sounds. This does not work reliably: the loudness a microphone picks up
depends on the weapon, the ammunition, which way the barrel was pointing, the
terrain, and the weather. Two shots fired from the exact same spot with two
different weapons can sound completely different in loudness by the time
they reach a listener 300 metres away. Any system that estimates range from
loudness alone is making an educated guess and presenting it as a
measurement — and this project deliberately refuses to do that.

Instead, this project uses a genuinely clever piece of physics: **most
rifle bullets travel faster than the speed of sound.** A bullet moving
faster than sound drags a small sonic boom behind it — the same physics
behind the "crack" you hear from a passing supersonic jet. This shockwave
is a completely separate sound event from the gun's muzzle blast (the
"bang"), and it arrives at a microphone *before* the bang does, and from
a slightly different direction.

That tiny difference — in timing, and in direction — turns out to contain
everything needed to work out how far away the shooter is, **without
needing to know what weapon was used.** This is the heart of the project,
and is explained properly in Section 5.

---

## 3. The Big Picture: How a Shot Gets Detected and Located

Here is the full journey, start to finish, in plain terms:

```
   GUNSHOT (muzzle blast + supersonic shockwave)
                    |
                    v
         Microphones pick up the sound
                    |
                    v
   Is this actually a gunshot? (yes/no decision)
                    |
        [ NO  -> stop here, nothing else happens ]
        [ YES -> continue ]
                    |
                    v
        Which direction did it come from?
                    |
                    v
   Was the bullet supersonic, and close enough to
   catch both the "crack" and the "bang"?
                    |
        [ YES -> work out direction AND distance ]
        [ NO  -> direction only, distance left blank ]
                    |
                    v
   If more than one listening team heard the shot,
   combine everyone's information into one best answer
                    |
                    v
        Final result: direction, distance,
        map position, and a confidence score
```

Every stage of this pipeline exists in working, tested code (not just a
design document) and is explained in its own section below.

---

## 4. Section: Is It Actually a Gunshot? (Classification)

Before any direction or distance math runs, the system has to answer a
simpler but more important question: *is this sound even a gunshot?* A
firecracker, a door slamming, a car backfiring, and a real gunshot can all
sound similar to a simple energy detector — sharp, sudden, loud.

The system measures about two dozen properties of the sound it picked up:
how quickly it rises to full volume, how it fades away, what frequencies it
contains, and (importantly) some properties specific to the shockwave shape
described above, since a shockwave has a distinctive "sharp spike then
mirror-image dip" shape that a firecracker's blast doesn't share.

These properties are fed into a trained model — not a hand-written rule,
but a decision system trained on many examples — which outputs a
probability: "92% likely this is a gunshot." If that number is too low, the
system stops right there. No direction, no distance, nothing shown on a
screen. This matters a lot in practice: a system that lights up a
commander's map for every door slam and firecracker within earshot quickly
gets ignored, and an ignored warning system is a useless one.

**Tested result (on simulated data):** correctly identifies about 98% of
real gunshots, while rejecting firecrackers, engines, and footsteps with a
very low false-alarm rate.

---

## 5. Section: Finding the Direction (and, When Possible, the Distance)

This is the technical core of the whole project, so it's worth explaining
carefully and patiently.

### 5a. Direction is the "easy" part

If you have several microphones spread a small distance apart, sound reaches
each one at a very slightly different moment — the same reason your two
ears can tell if someone is speaking from your left or right. By measuring
those tiny timing differences across all the microphone pairs, some
straightforward geometry (no guessing, no machine learning — just solving a
system of equations) gives a compass bearing to where the sound came from,
typically accurate to under a degree.

### 5b. Distance is the genuinely hard part — and where this project does
something distinctive

As explained in Section 2, most supersonic rifle rounds produce **two**
separate sounds: the shockwave ("crack") and the muzzle blast ("bang"). A
microphone close enough to the bullet's path hears both.

Here's the key insight, explained step by step:

- The **speed** the shockwave cone spreads out at is set purely by how fast
  the bullet is going. A faster bullet makes a *narrower* cone; a slower
  (but still supersonic) bullet makes a *wider* cone.
- Because the crack and the bang arrive from measurably different
  directions, the **angle between those two directions** tells you almost
  exactly how fast the bullet was going — this is pure geometry, and it does
  not care what gun or ammunition produced the shot.
- Once the bullet's speed is known, the **time gap** between hearing the
  crack and hearing the bang tells you how far away the shooter was — a bit
  like counting seconds between lightning and thunder, except here it's two
  sounds from one bullet instead of one flash and one boom.
- A third measurement — the exact shape of the crack sound itself — gives a
  rough estimate of exactly how close the bullet passed by (its "miss
  distance"), as a bonus.

Put together, a **single** microphone team that hears both sounds clearly
can work out the shooter's direction, distance, and the bullet's speed —
all at once, and without ever needing to know what weapon fired the shot.
That last property is what makes this approach genuinely useful in the
field: a system that has to recognise a weapon's specific sound signature
to work is fragile and easy to fool; this system works from physics alone.

**When this doesn't work:** if the shot came from too far away, or the
bullet was subsonic (some pistol rounds, for instance), the crack either
never reaches the microphone or can't be told apart from the bang. In that
case, the system is honest about it: it reports the direction only, and
leaves distance blank rather than guessing. A wrong number is worse than an
honest "I don't know," and this principle is applied everywhere in the
project, not just here.

---

## 6. Section: Multiple Teams Working Together (Fusion)

A single listening post is useful, but several listening posts working
together are far more powerful — and far more trustworthy. This project's
"fusion" layer is what combines everyone's information into one final
answer, and it follows one hard rule throughout: **never silently trust one
source of information over another. Cross-check everything, and say so
plainly when two measurements disagree.**

Concretely, when a shot is heard by more than one location, up to three
independent ways of estimating distance can exist at once:

1. The crack/bang method described above, from any one team that heard both
   sounds clearly.
2. Simple triangulation — if two or more teams each report a direction, the
   point where those direction-lines cross is the shooter's position.
3. A comparison between a flash of light from the muzzle and the bang, if an
   optical sensor is present (light is effectively instant compared to
   sound, so the light-to-bang time gap gives yet another independent range
   estimate).

If two or more of these methods land on similar answers, the system
combines them — giving more weight to whichever measurement is more
precise — into one tighter, more confident final answer. If the methods
land on *noticeably different* answers, the system does **not** quietly
average them together and hope for the best. It flags the disagreement
openly, and falls back to whichever single measurement it trusts most,
rather than presenting a confident-looking number that's actually a blend
of a good measurement and a bad one.

This same "don't silently trust one thing" philosophy also shows up one
level down: when the direction-finding math is looking at 15 different pairs
of microphones and one of those 15 measurements looks like an outlier
(likely caused by an echo off a nearby wall), the system detects and drops
that one bad measurement before it can drag the final answer off course.

---

## 7. Section: The Final Output

Once everything above has run, what actually gets shown is deliberately
simple and clean — five pieces of information, no more:

```json
{
  "direction": "N42.0E",
  "range_m": 300.1,
  "latitude": 28.616949,
  "longitude": 77.211075,
  "accuracy_pct": 87.3
}
```

- **direction** — a compass bearing, written the way a map-reader or
  surveyor would naturally say it out loud ("42 degrees east of north"),
  rather than a bare number that has to be mentally translated.
- **range_m** — distance to the shooter in metres, or left blank if the shot
  was out of range for the crack/bang method and no other team could
  triangulate it.
- **latitude / longitude** — the shooter's estimated position, ready to be
  dropped directly onto a map.
- **accuracy_pct** — an honest confidence score. This is *not* a made-up
  number: it comes from deliberately testing how much the estimate would
  wobble if the raw measurements had been very slightly noisier, and reports
  how tight or loose the fix actually is.

This is intentionally the *entire* output. A commander in the field, or a
piece of mapping software receiving this over a network, does not need — and
should not have to wade through — internal detail like which specific
mathematical method produced the answer. That detail still exists
internally for engineers and for debugging, it's simply not part of what
gets sent out.

---

## 8. Section: Built to Fail Honestly, Not Silently

A theme runs through every part of this project, worth calling out on its
own: **the system is designed to say "I don't know" rather than invent an
answer.**

A few concrete examples of this, all of which are enforced in the actual
code, not just described in a design document:

- If a microphone array is physically flat (no height difference between
  microphones), it is mathematically impossible for it to tell whether a
  sound came from above or below. The system refuses to report an "up/down"
  angle in that case, rather than quietly making one up.
- If a bullet was subsonic, or the shot happened too far away for the
  crack/bang method to work, distance is left blank — not filled in with a
  rough guess dressed up as a real number.
- If two independent range estimates disagree by more than a reasonable
  margin, that disagreement is reported explicitly, instead of being
  smoothed over by averaging.
- Near a certain narrow range of bullet speeds (just barely faster than
  sound), the geometry math becomes mathematically unstable and small
  measurement errors get wildly amplified. This was actually discovered by
  stress-testing the system with a large number of randomised inputs — not
  predicted in advance — and the system now explicitly flags this specific
  situation as low-confidence rather than reporting a wildly wrong number
  with a falsely reassuring confidence score.

This mindset — under-promise, and be transparent about uncertainty — is
what separates a system a commander can actually trust from one that just
produces impressive-looking numbers.

---

## 9. How Thoroughly This Has Been Tested

Everything described above is backed by an automated test suite (60 tests
at time of writing) and by large-scale randomised stress-testing, not just
a handful of hand-picked demo examples. A few concrete results from that
testing:

- Across **1,000+ randomly generated, deliberately noisy simulated shots**,
  direction was accurate to within about 1–2 degrees almost every time, and
  distance was typically accurate to within roughly 5–8% when the crack/bang
  method could be used.
- The system correctly told the difference between "close enough to measure
  distance" and "too far away, direction only" with **100% accuracy** across
  those trials.
- The gunshot/not-gunshot classifier caught about **98%** of real gunshots
  while correctly rejecting firecrackers, engines, footsteps, and other
  everyday sounds.
- When the fusion layer reported that two independent range measurements
  *agreed* with each other, the real-world error in that combined estimate
  was, on average, roughly **half** what it was in cases where the system
  had flagged a disagreement — direct proof that the disagreement-flagging
  mechanism is catching genuinely lower-quality fixes, not just adding noise.

---

## 10. What's Still a Work in Progress

In the interest of the same honesty this project tries to build in
everywhere else: a few things are deliberately not finished yet.

- **No physical hardware exists.** Every microphone signal in this project
  is generated by a physics simulation, not recorded from a real weapon.
- **No wireless network layer.** The system produces the exact structured
  data a real radio network would need to broadcast between teams, but the
  actual radio transmission part is out of scope for this stage of the
  project.
- **A visual dashboard is in progress**, separate from the detection and
  math engine described here, so that the numbers above can be shown on an
  actual map in real time rather than just printed as text.

---

## 11. Why This Matters — The Practical Case

Step back from the algorithms for a moment and consider the actual
situation this is built for: a soldier or a security team is under fire,
and the single most valuable piece of information in that moment is
"**where is the danger, and how far away is it?**" Every second spent
figuring that out by ear, or by guesswork, is a second of exposure.

What this project demonstrates is that a genuinely useful answer to that
question does not require expensive, exotic hardware or classified
military-grade sensors. It requires:

- A handful of ordinary microphones,
- Solid, well-tested physics and geometry (not a black-box AI guess), and
- The discipline to report honest uncertainty instead of a confident-sounding
  wrong answer.

The specific technique at the heart of this project — reading a bullet's
speed and the shooter's range directly from the geometry of its own
shockwave, rather than from a database of "what different guns sound like"
— is what makes the system **weapon-agnostic**. It doesn't need to be
told, trained on, or updated for every new rifle or ammunition type that
might be used against it, which is precisely the kind of assumption a real
adversary would try to exploit against a less careful system.

Beyond the immediate military and law-enforcement use case this was
designed for, the same underlying idea — multiple simple sensors,
physics-based cross-checking, and honest confidence reporting instead of
guesswork — has real value anywhere sound needs to be traced back to its
source under uncertainty: campus and public-safety shot-detection systems,
industrial safety monitoring for equipment failures, wildlife and
poaching-detection acoustic networks, and any other setting where "where
did that sound come from, and can we trust this estimate" is a question
worth answering carefully rather than quickly.
