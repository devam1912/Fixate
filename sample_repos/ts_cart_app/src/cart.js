/** Shopping cart pricing rules. */

export function applyDiscount(price, discountPercent) {
  // INTENTIONAL BUG: subtracts the percentage value directly instead of
  // computing the percentage of the price.
  return price - discountPercent;
}

export function cartTotal(items) {
  return items.reduce((sum, item) => sum + item.price * item.quantity, 0);
}
