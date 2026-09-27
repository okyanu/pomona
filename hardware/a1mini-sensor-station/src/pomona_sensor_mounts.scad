// Pomona sensor mounts V6.3 for the Hydro V2 / Soil V1 station rail.
// Licence: Apache-2.0 (same as the Pomona repository).
//
// Every mount slides onto the station's external T-rail (head 11.0 x 1.6 mm, neck 8.0 mm)
// through the locked MASTER_RAIL_030 socket (0.30 mm total clearance, fit-tested in V5.7).
//
// Coordinates: the socket's back face (towards the vessel) is x = -1.4, its front face
// x = +3.4. Everything else is built in front of x = FRONT - OVERLAP, so nothing can reach
// into the rail slot or behind the socket into the vessel wall.
//
// V6.3 fixes (V5.9-V6.2 had the probe rings centred inside the socket): ring centres now sit
// in front of the socket; hose opening faces away from the vessel with clearance; vented,
// roofed SHT31 cage; moisture slot sized for 23 mm capacitive boards. Edit the parameters
// below for your own parts.
//
// Render one part:   openscad -o ph.stl -D 'part="ph"' pomona_sensor_mounts.scad
// Parts: rail_fit, ph, ds18b20, hose, moisture, sht31, plate

$fn = 96;
part = "plate";

// ---- your parts (mm) -----------------------------------------------------------------
PH_PROBE_D = 12.0;       // analog pH probe body
DS_PROBE_D = 6.0;        // waterproof DS18B20 sleeve
HOSE_OD = 6.0;           // aquarium airline tubing outer diameter
MOIST_BOARD_W = 23.0;    // capacitive soil moisture board (v1.2 / v2.0) width
MOIST_BOARD_T = 1.6;     // board thickness (the slot clamps the board strip below the electronics)
SHT_POCKET = [20, 12, 16];   // SHT31 module pocket: x (depth), y (width), z (height)

// ---- print tuning ---------------------------------------------------------------------
PROBE_CLEAR = 0.6;       // diameter clearance for round probes
HOSE_CLEAR = 0.4;
SLOT_CLEAR = 0.6;
WALL = 2.7;
OVERLAP = 1.0;           // how far mount bodies fuse into the socket's front face

// ---- locked rail socket (do not change: matches the printed V5.7 fit test) -------------
FRONT = 3.4;
module MASTER_RAIL_030(h = 22) {
    total_clearance = 0.30;
    c = total_clearance / 2;
    difference() {
        translate([-1.4, -7.2, 0]) cube([4.8, 14.4, h]);
        translate([-0.10, -5.5 - c, -0.1]) cube([1.6 + 0.20 + c, 11 + 2 * c, h + 0.2]);
        translate([-1.5, -4 - c, -0.1]) cube([1.7, 8 + 2 * c, h + 0.2]);
    }
}

// A vertical sleeve in front of the socket, joined to it by a web that stays outside the bore.
module sleeve(bore_d, h, socket_h) {
    outer_r = bore_d / 2 + WALL;
    web = min(5, 0.4 * bore_d);
    translate([FRONT - OVERLAP + outer_r, 0, 0])
        difference() {
            cylinder(r = outer_r, h = h);
            translate([0, 0, -0.1]) cylinder(d = bore_d, h = h + 0.2);
        }
    translate([FRONT - OVERLAP, -web, 0]) cube([WALL, 2 * web, socket_h]);
}

module ph() {
    MASTER_RAIL_030(28);
    sleeve(PH_PROBE_D + PROBE_CLEAR, 40, 28);
}

module ds18b20() {
    MASTER_RAIL_030(22);
    sleeve(DS_PROBE_D + PROBE_CLEAR, 28, 22);
}

// Vertical C-sleeve: the airline runs up the station wall and snaps in from the front
// (away from the vessel) through an opening 80 % of the hose diameter. Printed upright,
// so it needs no supports.
module hose() {
    bore = HOSE_OD + HOSE_CLEAR;
    outer_r = bore / 2 + WALL;
    h = 16;
    difference() {
        union() {
            MASTER_RAIL_030(h);
            sleeve(bore, h, h);
        }
        translate([FRONT - OVERLAP + outer_r, -0.4 * HOSE_OD, -0.1]) cube([outer_r + 1, 0.8 * HOSE_OD, h + 0.2]);
    }
}

// Board slides down through a slot parallel to the vessel wall.
module moisture() {
    slot_w = MOIST_BOARD_W + SLOT_CLEAR;
    slot_t = MOIST_BOARD_T + SLOT_CLEAR;
    body = [slot_t + 2 * WALL, slot_w + 2 * WALL, 30];
    MASTER_RAIL_030(22);
    translate([FRONT - OVERLAP, -body[1] / 2, 0])
        difference() {
            cube(body);
            translate([WALL, WALL, -0.1]) cube([slot_t, slot_w, body[2] + 0.2]);
        }
}

// Post with a vented, roofed cage: open at the front for the module and cable, slots on both
// sides for airflow, a roof against drips. A 45-degree cone under the cage and a tapered base
// keep the whole part printable without supports.
module sht31() {
    stem = [8, 6, 62];
    cage = [SHT_POCKET[0] + 4, SHT_POCKET[1] + 4, SHT_POCKET[2] + 4];
    z0 = stem[2] - 2;
    reach = max(cage[0] - stem[0], (cage[1] - stem[1]) / 2);
    MASTER_RAIL_030(22);
    translate([FRONT - OVERLAP, -stem[1] / 2, 0]) cube(stem);
    // tapered base: wide at the bed, narrowing to the stem (each layer inside the one below)
    translate([FRONT - OVERLAP, -stem[1] / 2, 0])
        linear_extrude(height = 30, scale = [stem[0] / (stem[0] + 10), 1]) square([stem[0] + 10, stem[1]]);
    // 45-degree cone from the stem out to the cage floor
    hull() {
        translate([FRONT - OVERLAP, -stem[1] / 2, z0 - reach - 1]) cube([stem[0], stem[1], 0.01]);
        translate([FRONT - OVERLAP, -cage[1] / 2, z0]) cube([cage[0], cage[1], 0.01]);
    }
    translate([FRONT - OVERLAP, -cage[1] / 2, z0])
        difference() {
            cube(cage);
            translate([2, 2, 2]) cube([SHT_POCKET[0] + 2.1, SHT_POCKET[1], SHT_POCKET[2]]);  // open front
            for (z = [5, 9, 13]) for (s = [-1, 1])
                translate([5, s < 0 ? -0.1 : cage[1] - 2.1, z]) cube([cage[0] - 8, 2.2, 2]);  // side vents
        }
}

module rail_fit() { MASTER_RAIL_030(12); }

// All mounts on one A1 mini plate (180 x 180 mm), each standing on Z = 0.
module plate() {
    translate([10, 20, 0]) rail_fit();
    translate([35, 20, 0]) ph();
    translate([70, 20, 0]) ds18b20();
    translate([100, 20, 0]) hose();
    translate([130, 30, 0]) moisture();
    translate([10, 70, 0]) sht31();
}

if (part == "rail_fit") rail_fit();
else if (part == "ph") ph();
else if (part == "ds18b20") ds18b20();
else if (part == "hose") hose();
else if (part == "moisture") moisture();
else if (part == "sht31") sht31();
else plate();
