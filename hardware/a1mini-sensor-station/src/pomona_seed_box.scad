// Pomona seed germination box V1: a row of cells (default 3), one 22 x 22 x 25 mm coco/sponge
// plug per cell, and a vented lid over all cells.
// Licence: Apache-2.0 (same as the Pomona repository).
//
// Each plug sits directly on the flat floor of its cell. Low dividers keep each cell's water
// separate: pour about 3 mm of water per cell and the plug wicks it up without being submerged.
// The lid plugs into the opening and has four vent holes over each cell; when the seedlings
// grow, lift the lid, prop it ajar, then remove it.
//
// Modelled in PRINT orientation, no supports:
//   box: floor on the bed, opening up.  lid: plate on the bed, plug pointing up.
//
// Render:  openscad -o box.stl -D 'part="box"' pomona_seed_box.scad
// Parts:   box, lid, plate (box + lid centred on a 180 mm A1 mini bed),
//          test_sponge (the plugs, to check the fit; do not print it)

$fn = 48;
part = "box";

// ---- size (mm) --------------------------------------------------------------------------
CELLS = 3;               // plugs side by side (up to 4 fit the A1 mini bed)
CELL = 34.0;             // inside width of one cell (square)
BOX_H = 32.0;            // body height; closed height = BOX_H + LID_T
WALL = 2.0;
FLOOR = 2.0;
DIV_T = 1.6;             // divider thickness
DIV_H = 10.0;            // divider height above the floor: separates water, stays below the lid plug
CORNER_R = 4.0;          // outer corner radius

// ---- sponge and water -------------------------------------------------------------------
SPONGE_W = 22.0;         // plug width and depth
SPONGE_H = 25.0;         // plug height

WATER_DEPTH = 3.0;       // suggested water depth per cell (not modelled)

// ---- lid ----------------------------------------------------------------------------------
LID_T = 2.0;
PLUG_CLEAR = 0.5;        // total clearance between plug and opening (printer dependent)
PLUG_H = 4.0;
PLUG_WALL = 1.6;
VENT_D = 2.5;
VENT_OFFSET = 8.0;       // four vents per cell at +-this from the cell centre, on the axes
TAB = [14, 6];           // lift tab beyond the lid edge: width, reach

IN = [CELLS * CELL + (CELLS - 1) * DIV_T, CELL];
OUT = IN + [2 * WALL, 2 * WALL];
function cell_x(i) = -IN[0] / 2 + CELL / 2 + i * (CELL + DIV_T);

assert(CELLS >= 1, "need at least one cell");
assert(OUT[0] <= 175, "too many cells for the A1 mini bed (180 mm)");
assert(BOX_H >= FLOOR + SPONGE_H + 4, "leave at least 4 mm above the plug for the seed");
assert(CELL > SPONGE_W + 2, "plug does not fit in a cell");
assert(DIV_H < BOX_H - PLUG_H - FLOOR, "dividers would hit the lid plug");

module rrect(size, r) {
    offset(r) square(size - [2 * r, 2 * r], center = true);
}
module rbox(size, r, h) {
    linear_extrude(h) rrect(size, r);
}

module box() {
    difference() {
        rbox(OUT, CORNER_R, BOX_H);
        translate([0, 0, FLOOR]) rbox(IN, CORNER_R - WALL, BOX_H);
    }
    for (i = [1 : CELLS - 1])
        translate([cell_x(i) - CELL / 2 - DIV_T, -IN[1] / 2 - 0.01, FLOOR - 0.01])
            cube([DIV_T, IN[1] + 0.02, DIV_H + 0.01]);
}

module lid() {
    plug = IN - [PLUG_CLEAR, PLUG_CLEAR];
    // plate
    difference() {
        union() {
            rbox(OUT, CORNER_R, LID_T);
            // lift tab on -y
            translate([-TAB[0] / 2, -OUT[1] / 2 - TAB[1], 0]) cube([TAB[0], TAB[1] + 2, LID_T]);
        }
        for (i = [0 : CELLS - 1], a = [0, 90, 180, 270])
            translate([cell_x(i), 0, -0.1]) rotate(a) translate([VENT_OFFSET, 0, 0])
                cylinder(d = VENT_D, h = LID_T + 0.2);
    }
    // plug ring (hollow, drops into the opening)
    translate([0, 0, LID_T - 0.01]) difference() {
        rbox(plug, CORNER_R - WALL, PLUG_H + 0.01);
        translate([0, 0, -0.1])
            rbox(plug - [2 * PLUG_WALL, 2 * PLUG_WALL], max(CORNER_R - WALL - PLUG_WALL, 0.5), PLUG_H + 0.3);
    }
}

module test_sponge() {
    for (i = [0 : CELLS - 1])
        translate([cell_x(i) - SPONGE_W / 2, -SPONGE_W / 2, FLOOR]) cube([SPONGE_W, SPONGE_W, SPONGE_H]);
}

module plate() {
    translate([90, 55, 0]) box();
    translate([90, 125, 0]) lid();
}

if (part == "box") box();
else if (part == "plate") plate();
else if (part == "lid") lid();
else if (part == "test_sponge") test_sponge();
