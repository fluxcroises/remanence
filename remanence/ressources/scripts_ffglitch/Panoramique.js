// D'après mv_pan.js de ffglitch-scripts (Ramiro Polla, domaine public, Unlicense).
// Ajoute le même déplacement à tous les vecteurs.

const pan_x = 1;
const pan_y = 0;

export function setup(args)
{
  args.features = ["mv"];
}

export function glitch_frame(frame)
{
  const fwd_mvs = frame.mv?.forward;
  if (!fwd_mvs)
    return;
  frame.mv.overflow = "truncate";
  fwd_mvs.add(MV(pan_x, pan_y));
}
