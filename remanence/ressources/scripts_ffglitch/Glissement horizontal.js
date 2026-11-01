// D'après mv_sink_and_rise.js de ffglitch-scripts (Ramiro Polla, domaine public, Unlicense),
// sur l'autre axe. Le mouvement vertical disparaît : l'image ne fait plus que glisser.

export function setup(args)
{
  args.features = ["mv"];
}

export function glitch_frame(frame)
{
  const fwd_mvs = frame.mv?.forward;
  if (!fwd_mvs)
    return;
  fwd_mvs.assign_v(0);
}
