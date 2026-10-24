export type MockProduct = {
  name: string;
  price: number;
  merchant: string;
};

const CATALOGS: { pattern: RegExp; products: MockProduct[] }[] = [
  {
    pattern: /headphone|earbud|headset/i,
    products: [
      { name: "Anker Soundcore Q20i", price: 49.99, merchant: "Amazon" },
      { name: "JBL Tune 770NC", price: 99.99, merchant: "Walmart" },
      { name: "Sony WH-CH720N", price: 128, merchant: "Best Buy" },
      { name: "Bose QuietComfort", price: 249, merchant: "Bose" },
    ],
  },
  {
    pattern: /laptop|notebook|macbook/i,
    products: [
      { name: "Acer Aspire Go 15", price: 429, merchant: "Best Buy" },
      { name: "Lenovo IdeaPad Slim 3", price: 549, merchant: "Lenovo" },
      { name: "Apple MacBook Air 13", price: 999, merchant: "Apple" },
    ],
  },
  {
    pattern: /shoe|sneaker|boot/i,
    products: [
      { name: "Adidas Grand Court", price: 55, merchant: "Adidas" },
      { name: "New Balance 574", price: 89.99, merchant: "Nordstrom" },
      { name: "Nike Pegasus 41", price: 140, merchant: "Nike" },
    ],
  },
  {
    pattern: /coffee|espresso/i,
    products: [
      { name: "Hamilton Beach FlexBrew", price: 69.99, merchant: "Target" },
      { name: "Ninja Specialty Coffee Maker", price: 129.99, merchant: "Walmart" },
      { name: "Breville Bambino", price: 299.95, merchant: "Williams Sonoma" },
    ],
  },
];

function genericProducts(query: string): MockProduct[] {
  const label = query.replace(/\s+/g, " ").trim();
  const short = label.length > 48 ? `${label.slice(0, 45)}…` : label;

  return [
    { name: `${short} — value pick`, price: 24.99, merchant: "Target" },
    { name: `${short} — everyday pick`, price: 46, merchant: "Walmart" },
    { name: `${short} — higher-rated pick`, price: 79, merchant: "Amazon" },
  ];
}

function roundMoney(value: number): number {
  return Math.round(value * 100) / 100;
}

export function mockProducts(
  query: string,
  budget: number,
  quality: number,
): MockProduct[] {
  const match = CATALOGS.find((entry) => entry.pattern.test(query));
  const templates = (match ? match.products : genericProducts(query)).map(
    (item) => ({ ...item }),
  );
  const affordable = templates.filter((item) => item.price <= budget);

  let items: MockProduct[];
  if (affordable.length >= 2) {
    items = affordable;
  } else {
    const maxPrice = Math.max(...templates.map((item) => item.price));
    const scale = (budget / maxPrice) * 0.96;
    items = templates.map((item) => ({
      ...item,
      price: roundMoney(Math.max(1, item.price * scale)),
    }));
  }

  if (quality <= 33) {
    return items.slice(0, 2);
  }

  if (quality >= 67) {
    return items.slice(-3);
  }

  return items.slice(0, 3);
}
