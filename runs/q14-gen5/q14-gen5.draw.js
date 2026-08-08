var PERIOD = 4.0;
var READOUTS = ["r90", "v_r90", "r30", "z30"];

function drawFrame(ps, u, svg) {
  var c2 = ps[CASES[1]];          // B=B0/2：电子落到筒壁的情形（题目所求）
  var phi = u * Math.PI / 2;      // 所有电子横向相位相同，位于同一旋转半径线上

  // ---- 轴截面（Panel A）映射：O=(80,205)，z 向右、r 向上 ----
  var AX = 80, AY = 205, SZ = 115.1605, SR = 110;
  // 电子到达筒壁即停（钳制 r≤1=R）
  var r90 = c2.r90 > 1 ? 1 : c2.r90;
  var r30 = c2.r30 > 1 ? 1 : c2.r30;
  var r20 = c2.r20 > 1 ? 1 : c2.r20;
  // z20 不是探针量（探针只给 r20/v20），按物理关系 z=t·v0·cosθ 自算
  var z20 = u * Math.PI * Math.cos(Math.PI / 9);

  // 轴截面上的电子
  svg.querySelector('#q14-gen5-dot90a').setAttribute('cx', AX);
  svg.querySelector('#q14-gen5-dot90a').setAttribute('cy', AY - r90 * SR);
  svg.querySelector('#q14-gen5-dot30a').setAttribute('cx', AX + c2.z30 * SZ);
  svg.querySelector('#q14-gen5-dot30a').setAttribute('cy', AY - r30 * SR);
  svg.querySelector('#q14-gen5-dot20a').setAttribute('cx', AX + z20 * SZ);
  svg.querySelector('#q14-gen5-dot20a').setAttribute('cy', AY - r20 * SR);

  // 筒壁落点带状区域：沿壁（r=R）从 z=0 铺到当前 θ=30° 电子到达的 z
  var beltW = c2.z30 * SZ;
  if (beltW < 0) beltW = 0;
  if (beltW > 313.3) beltW = 313.3;
  svg.querySelector('#q14-gen5-belt').setAttribute('width', beltW);

  // ---- 横截面（Panel B）映射：圆心(470,160)，壁半径 70 ----
  var CX = 470, CY = 160, RW = 70;
  var co = Math.cos(phi), si = Math.sin(phi);
  // 旋转径向线
  svg.querySelector('#q14-gen5-ray').setAttribute('x2', CX + RW * co);
  svg.querySelector('#q14-gen5-ray').setAttribute('y2', CY + RW * si);
  // 横截面上的电子（同一半径线上，半径各不相同）
  svg.querySelector('#q14-gen5-dot90b').setAttribute('cx', CX + r90 * RW * co);
  svg.querySelector('#q14-gen5-dot90b').setAttribute('cy', CY + r90 * RW * si);
  svg.querySelector('#q14-gen5-dot30b').setAttribute('cx', CX + r30 * RW * co);
  svg.querySelector('#q14-gen5-dot30b').setAttribute('cy', CY + r30 * RW * si);
  svg.querySelector('#q14-gen5-dot20b').setAttribute('cx', CX + r20 * RW * co);
  svg.querySelector('#q14-gen5-dot20b').setAttribute('cy', CY + r20 * RW * si);

  // 筒壁落点高亮环：θ=90° 电子在 u=1/3 先到壁，θ=30° 在 u=1 到壁，之后全周渐显
  var op = (u - 0.33) / 0.67;
  if (op < 0) op = 0;
  if (op > 1) op = 1;
  svg.querySelector('#q14-gen5-arc').setAttribute('opacity', 0.85 * op);
}

function drawReset(svg) {
  drawFrame(probeAll(0), 0, svg);
}
