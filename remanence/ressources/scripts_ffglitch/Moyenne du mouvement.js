// D'après mv_average.js de ffglitch-scripts (Ramiro Polla, domaine public, Unlicense).
// Chaque image reprend la moyenne des vecteurs des images précédentes.

const tail_length = 10;

let prev_fwd_mvs = [];
let total_sum;

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
  const deep_copy = fwd_mvs.dup();
  prev_fwd_mvs.push(deep_copy);
  if (!total_sum)
    total_sum = new MV2DArray(fwd_mvs.width, fwd_mvs.height);
  if (prev_fwd_mvs.length > tail_length)
  {
    total_sum.sub(prev_fwd_mvs[0]);
    prev_fwd_mvs = prev_fwd_mvs.slice(1);
  }
  total_sum.add(deep_copy);
  if (prev_fwd_mvs.length == tail_length)
  {
    fwd_mvs.assign(total_sum);
    fwd_mvs.div(MV(tail_length, tail_length));
  }
}
