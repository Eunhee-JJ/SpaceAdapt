#!/usr/bin/env bash
# Synthetic room photos for demo/validation (FLUX.1-schnell, Apache-2.0, via mflux).
# Usage: scripts/gen_room_images.sh [seeds...]   (default seeds: 11 22)
set -euo pipefail
cd "$(dirname "$0")/../data/images"
MODEL=mflux-community/flux-1-schnell-mflux-q4
if [[ $# -gt 0 ]]; then SEEDS=("$@"); else SEEDS=(11 22); fi
COMMON="Realistic smartphone photo, wide-angle shot taken from the entrance corner at standing eye level, whole room visible, daylight, lived-in but tidy enough to see furniture clearly, no people, no text"

P_room_a="Small Korean studio apartment about 3 by 3 meters. A single bed against the left wall. A white desk directly facing the bed with two computer monitors and a keyboard on it, an office chair with wheels. A tall wardrobe with an overflowing clothes hanger rack beside it, clothes piled on the rack. A small kitchenette sink counter in the far right corner. A low cabinet right next to the entrance door. Window on the right wall. ${COMMON}"
P_room_b="Cozy small Korean studio room. A single bed placed right next to the entrance door. Thick blackout curtains on the window, a sleeping eye mask on the pillow. A rolled-up yoga mat leaning against the wall. A small desk under the window with a chair. A white built-in closet in the corner. A low storage cabinet. Warm dim light. ${COMMON}"
P_room_c="Narrow Korean university dormitory room for one person. A single bed along the left wall. A desk with a chair under the window at the far end. A wooden wardrobe near the door with a small white property tag sticker on it. A long low storage cabinet on caster wheels standing in the middle of the floor. Linoleum floor, fluorescent ceiling light. ${COMMON}"

prompt_for() { case "$1" in room-a) echo "$P_room_a";; room-b) echo "$P_room_b";; room-c) echo "$P_room_c";; esac; }

for room in room-a room-b room-c; do
  for s in "${SEEDS[@]}"; do
    out="${room}_s${s}.png"
    [[ -f "$out" ]] && { echo "skip $out"; continue; }
    mflux-generate --model "$MODEL" --base-model schnell --steps 4 \
      --width 1024 --height 768 --seed "$s" --prompt "$(prompt_for "$room")" --output "$out"
    echo "done $out"
  done
done
