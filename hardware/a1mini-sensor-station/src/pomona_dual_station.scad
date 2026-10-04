// Licence: Apache-2.0 (same as the Pomona repository). Designed by Okyanus for Pomona.
// Use part="hydro" or part="soil" from this file. The holder modules further down are the
// original V2 prototypes, kept for history; print the fixed ones from pomona_sensor_mounts.scad.
// Pomona compact dual station V1 - A1 mini friendly
// Uses existing seedling pot: body top 50 mm, rim 52 mm.
// Units: mm
$fn=120;
part="hydro"; // hydro, soil, ph_holder, ds_holder, sht_post, moisture_holder, hose_clip, plate

pot_hole_d=50.4;
rim_pocket_d=53.0;
rim_pocket_depth=1.2;
body_od=76;
wall=2.4;
bottom=2.8;
rail_w=8; rail_t=3; rail_h=35;

module rail(h=rail_h){
  // simple external dovetail-ish mounting rib; no penetration through vessel wall
  translate([body_od/2-0.2,-rail_w/2,8]) cube([rail_t,rail_w,h]);
  translate([body_od/2+rail_t-0.2,-(rail_w+3)/2,8]) cube([1.6,rail_w+3,h]);
}

module hydro(){
  h=70; straight=62; top_od=60;
  difference(){
    union(){
      cylinder(d=body_od,h=straight);
      translate([0,0,straight]) cylinder(h=h-straight,r1=body_od/2,r2=top_od/2);
      rotate([0,0,0]) rail(42);
      rotate([0,0,120]) rail(42);
      rotate([0,0,240]) rail(42);
    }
    // cavity
    translate([0,0,bottom]) cylinder(r=body_od/2-wall,h=straight-bottom+0.02);
    translate([0,0,straight]) cylinder(h=4.8,r1=body_od/2-wall,r2=27.5);
    translate([0,0,66.7]) cylinder(d=pot_hole_d,h=3.8);
    translate([0,0,h-rim_pocket_depth]) cylinder(d=rim_pocket_d,h=rim_pocket_depth+0.2);
  }
}

soil_h=40; // soil body height (V1 was 25); the pot seat and rim pocket stay at the top

module soil(){
  // Soil V2: soil body for the same 52 mm rim / 50 mm pot footprint, taller than the V1 tray.
  h=soil_h;
  assert(h>=25 && h<=120, "soil_h must be 25-120 mm");
  rail_len=h-10; // rails run from z=8 to 2 mm below the top
  difference(){
    union(){
      cylinder(d=body_od,h=h);
      rotate([0,0,0]) rail(rail_len);
      rotate([0,0,120]) rail(rail_len);
      rotate([0,0,240]) rail(rail_len);
    }
    translate([0,0,3]) cylinder(d=68,h=h-5.2);
    // center raised support/drain recess keeps pot centered
    translate([0,0,h-6]) cylinder(d=pot_hole_d,h=6.2);
    translate([0,0,h-rim_pocket_depth]) cylinder(d=rim_pocket_d,h=rim_pocket_depth+0.2);
    // drainage holes around pot area
    for(a=[0:45:315]) translate([20*cos(a),20*sin(a),-0.1]) cylinder(d=3,h=3.2);
  }
}

// Clip base that slides over external rail; intentionally does not pierce vessel.
module rail_socket(h=16){
  difference(){
    cube([7,15,h],center=false);
    translate([-0.1,3.5,-0.1]) cube([4.6,8,h+0.2]);
  }
}

module ph_holder(){
  // vertical ~12 mm probe holder attached to rail socket
  union(){
    rail_socket(28);
    translate([7,7.5,0]) difference(){cylinder(d=18,h=40); translate([0,0,-0.1]) cylinder(d=12.6,h=40.2);} 
  }
}
module ds_holder(){
  union(){
    rail_socket(22);
    translate([7,7.5,0]) difference(){cylinder(d=12,h=28); translate([0,0,-0.1]) cylinder(d=6.6,h=28.2);} 
  }
}
module sht_post(){
  union(){
    rail_socket(22);
    translate([7,5.5,0]) cube([7,4,65]);
    translate([4,1.5,58]) difference(){cube([24,12,18]); translate([2,2,2]) cube([20,8,16.2]);}
  }
}
module moisture_holder(){
  union(){
    rail_socket(22);
    translate([7,1.5,0]) difference(){cube([16,12,48]); translate([3,2,-0.1]) cube([10,8,48.2]);}
  }
}
module hose_clip(){
  union(){
    rail_socket(16);
    translate([8,7.5,8]) rotate([90,0,0]) difference(){cylinder(d=12,h=5,center=true); cylinder(d=6,h=6,center=true); translate([-6,-6,-3]) cube([6,12,6]);}
  }
}

module plate(){
  // Arrangement sized for 180x180 A1 mini bed: both vessels + small holders.
  translate([-45,0,0]) hydro();
  translate([45,0,0]) soil();
  translate([-70,58,0]) ph_holder();
  translate([-40,60,0]) ds_holder();
  translate([0,55,0]) hose_clip();
  translate([28,53,0]) moisture_holder();
  translate([62,50,0]) sht_post();
}

if(part=="hydro") hydro();
else if(part=="soil") soil();
else if(part=="ph_holder") ph_holder();
else if(part=="ds_holder") ds_holder();
else if(part=="sht_post") sht_post();
else if(part=="moisture_holder") moisture_holder();
else if(part=="hose_clip") hose_clip();
else if(part=="plate") plate();
