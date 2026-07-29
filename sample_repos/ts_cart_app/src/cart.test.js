import { describe, it, expect } from 'vitest';
import { applyDiscount, cartTotal } from './cart.js';

describe('cart', () => {
  it('applies a percentage discount', () => {
    expect(applyDiscount(200, 10)).toBe(180);
  });

  it('sums line items', () => {
    expect(cartTotal([{ price: 5, quantity: 2 }, { price: 3, quantity: 1 }])).toBe(13);
  });
});
