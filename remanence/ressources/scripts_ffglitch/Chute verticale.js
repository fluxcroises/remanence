// D'après mv_sink_and_rise_fast.js de ffglitch-scripts (Ramiro Polla, domaine public,
// Unlicense). Le mouvement horizontal disparaît : l'image ne fait plus que monter ou tomber.

export function setup(args)
{
  args.features = ["mv"];
}

export function glitch_frame(frame)
{
  const fwd_mvs = frame.mv?.forward;
  if (!fwd_mvs)
    return;
  fwd_mvs.assign_h(0);
}
