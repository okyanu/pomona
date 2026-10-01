// Pomona probe lid V1: a lid for a round reservoir with the seedling-pot seat and probe ports.
// Licence: Apache-2.0 (same as the Pomona repository).
//
// Fixes the V6.3 limitation that rail mounts hold probes beside the station, not in the water,
// and gives more than the Hydro V2's 0.24 L: put this lid on any round container (deli tub,
// bucket, food box) and the probes hang straight into the solution.
//
// Modelled in PRINT orientation: the lid's top face lies on the bed at z = 0; the skirt and
// probe sleeves grow upwards (in use they point down into the container). No supports.
// The pot seat is a ~50 degree cone, so it prints without overhang.
//
// Render:  openscad -o lid.stl -D 'part="lid"' pomona_probe_lid.scad
// Parts:   lid, fit_ring (a thin skirt-only ring to test the container fit first)

$fn = 120;
part = "lid";

// ---- your container (mm) ----------------------------------------------------------------
CONTAINER_ID = 110.0;    // inside diameter of the container opening (measure it)
FIT_CLEAR = 0.6;         // diameter clearance between skirt and opening
RIM_OVERHANG = 4.0;      // how far the lid rests on the container rim
SKIRT_H = 10.0;          // how deep the skirt drops into the opening

// ---- your parts (mm), same defaults as pomona_sensor_mounts.scad --------------------------
PH_PROBE_D = 12.0;
DS_PROBE_D = 6.0;
HOSE_OD = 6.0;
LEVEL_PORT_D = 8.4;      // vertical float switch (M8 thread); 0 = no port
PROBE_CLEAR = 0.6;
HOSE_CLEAR = 0.4;

// ---- pot seat: same seedling pot as the station (50 mm body, 52 mm rim) --------------------
POT_HOLE_D = 50.4;
RIM_SEAT_D = 53.2;       // top of the 45 degree seat cone

// ---- shape ------------------------------------------------------------------------------
LID_T = 3.0;
SKIRT_WALL = 2.0;
SLEEVE_H = 18.0;         // sleeve length below the lid (from the lid's underside)
WALL = 2.7;
RIB = 0.4;               // crush ribs: radial reach into the bore for a light grip
TAB = [14, 10];          // lift tab beyond the rim: width, reach

LID_D = CONTAINER_ID + 2 * RIM_OVERHANG;
assert(CONTAINER_ID >= 90, "the pot and probe ports need a container opening of at least 90 mm");
assert(LID_D + TAB[1] <= 178, "lid too large for the A1 mini bed (180 mm)");
SKIRT_OD = CONTAINER_ID - FIT_CLEAR;

// Port layout (x, y): the pot sits off-centre so the probes fit beside it.
POT_XY = [-0.14 * CONTAINER_ID, 0];
PH_XY = [0.27 * CONTAINER_ID, 0];
DS_XY = [0.20 * CONTAINER_ID, 0.20 * CONTAINER_ID];
HOSE_XY = [0.20 * CONTAINER_ID, -0.20 * CONTAINER_ID];
LEVEL_XY = [0.06 * CONTAINER_ID, 0.36 * CONTAINER_ID];

PH_BORE = PH_PROBE_D + PROBE_CLEAR;
DS_BORE = DS_PROBE_D + PROBE_CLEAR;
HOSE_BORE = HOSE_OD + HOSE_CLEAR;

module sleeve(xy, bore, ribs) {
    translate([xy[0], xy[1], 0]) difference() {
        cylinder(d = bore + 2 * WALL, h = LID_T + SLEEVE_H);
        translate([0, 0, -0.1]) cylinder(d = bore, h = LID_T + SLEEVE_H + 0.2);
    }
    // Three vertical crush ribs inside the bore, below the lid plate. Each starts with a cone
    // so its lower end does not hang flat over the hole.
    if (ribs) for (a = [90, 210, 330])
        translate([xy[0] + (bore / 2 + 0.6 - RIB) * cos(a), xy[1] + (bore / 2 + 0.6 - RIB) * sin(a), LID_T + 0.2]) {
            cylinder(d1 = 0.01, d2 = 1.2, h = 1.0, $fn = 24);
            translate([0, 0, 1.0]) cylinder(d = 1.2, h = SLEEVE_H - 1.2, $fn = 24);
        }
}

module lid_plate() {
    cylinder(d = LID_D, h = LID_T);
    // Small rounded lift tab on the rim.
    hull() {
        translate([LID_D / 2 - 4, -TAB[0] / 2, 0]) cube([1, TAB[0], LID_T]);
        for (y = [-1, 1]) translate([LID_D / 2 + TAB[1] - 3, y * (TAB[0] / 2 - 3), 0]) cylinder(r = 3, h = LID_T, $fn = 32);
    }
}

module skirt(h = SKIRT_H) {
    translate([0, 0, LID_T - 0.01]) difference() {
        cylinder(d = SKIRT_OD, h = h + 0.01);
        translate([0, 0, -0.1]) cylinder(d = SKIRT_OD - 2 * SKIRT_WALL, h = h + 0.2);
    }
}

module lid() {
    difference() {
        union() {
            lid_plate();
            skirt();
            sleeve(PH_XY, PH_BORE, true);
            sleeve(DS_XY, DS_BORE, true);
            sleeve(HOSE_XY, HOSE_BORE, false);
        }
        // Pot hole and conical rim seat (on the top face, i.e. at the bed).
        translate([POT_XY[0], POT_XY[1], -0.1]) cylinder(d = POT_HOLE_D, h = LID_T + 0.2);
        translate([POT_XY[0], POT_XY[1], -0.01])
            cylinder(d1 = RIM_SEAT_D, d2 = POT_HOLE_D - 0.2, h = 0.6 * (RIM_SEAT_D - POT_HOLE_D + 0.2));  // ~50 deg
        for (p = [[PH_XY, PH_BORE], [DS_XY, DS_BORE], [HOSE_XY, HOSE_BORE]])
            translate([p[0][0], p[0][1], -0.1]) cylinder(d = p[1], h = LID_T + 0.2);
        if (LEVEL_PORT_D > 0)
            translate([LEVEL_XY[0], LEVEL_XY[1], -0.1]) cylinder(d = LEVEL_PORT_D, h = LID_T + 0.2);
    }
}

// Print this first (about 10 minutes): rim and skirt only, to check the container fit.
module fit_ring() {
    difference() {
        union() {
            cylinder(d = LID_D, h = 1.2);
            translate([0, 0, 1.19]) difference() {
                cylinder(d = SKIRT_OD, h = 6);
                translate([0, 0, -0.1]) cylinder(d = SKIRT_OD - 2 * SKIRT_WALL, h = 6.2);
            }
        }
        translate([0, 0, -0.1]) cylinder(d = SKIRT_OD - 2 * SKIRT_WALL, h = 1.4);
    }
}

if (part == "lid") lid();
else if (part == "fit_ring") fit_ring();
