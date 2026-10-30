// Run with: node --experimental-strip-types --test src/geometry.test.ts
// @ts-ignore Node test runner is only required at test time.
import {test} from 'node:test';
// @ts-ignore Node assert is only required at test time.
import assert from 'node:assert/strict';
import {selectionRect,effectFrameAt} from './geometry.ts';
test('selection clamps both endpoints before measuring repair authorization',()=>{
  assert.deepEqual(selectionRect({x:10,y:10},{x:-10,y:-8},32,32),{x:0,y:0,width:11,height:11});
  assert.deepEqual(selectionRect({x:10,y:10},{x:500,y:600},32,32),{x:10,y:10,width:22,height:22});
});
test('one pixel selections remain one pixel',()=>assert.deepEqual(selectionRect({x:4,y:7},{x:4,y:7},32,32),{x:4,y:7,width:1,height:1}));
test('effect exposure uses left-closed right-open independent intervals',()=>{
  const d=[20,15,40];
  assert.equal(effectFrameAt(d,100,99),-1);
  assert.equal(effectFrameAt(d,100,100),0);
  assert.equal(effectFrameAt(d,100,120),1);
  assert.equal(effectFrameAt(d,100,135),2);
  assert.equal(effectFrameAt(d,100,175),-1);
});
