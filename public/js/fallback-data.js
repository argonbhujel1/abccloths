/**
 * Bundled fallback catalog & defaults.
 * Used when Neon is unavailable so the storefront remains functional.
 */
window.ABC_FALLBACK = {
  products: [
    {
      id: 9001,
      name: "Classic Oxford Shirt",
      price: 3490,
      image_url: "https://images.unsplash.com/photo-1596755094514-f87e34085b2c?w=600&h=750&fit=crop",
      description: "Crisp cotton oxford shirt with a clean modern fit. Perfect for work or weekend.",
      category: "men",
      colors: ["White", "Sky Blue", "Navy"],
      sizes: ["S", "M", "L", "XL"],
      active: true
    },
    {
      id: 9002,
      name: "Relaxed Linen Trousers",
      price: 4290,
      image_url: "https://images.unsplash.com/photo-1594938298603-c8148c4dae35?w=600&h=750&fit=crop",
      description: "Breathable linen trousers with a tapered silhouette and elastic comfort waist.",
      category: "men",
      colors: ["Beige", "Olive", "Charcoal"],
      sizes: ["S", "M", "L", "XL"],
      active: true
    },
    {
      id: 9003,
      name: "Silk Blend Blouse",
      price: 5190,
      image_url: "https://images.unsplash.com/photo-1564257631407-4deb1f99dbaa?w=600&h=750&fit=crop",
      description: "Fluid silk-blend blouse with soft drape and refined button details.",
      category: "women",
      colors: ["Ivory", "Blush", "Black"],
      sizes: ["XS", "S", "M", "L"],
      active: true
    },
    {
      id: 9004,
      name: "High-Rise Wide Leg Jeans",
      price: 4590,
      image_url: "https://images.unsplash.com/photo-1541099649105-f69ad21f3246?w=600&h=750&fit=crop",
      description: "Premium denim with a flattering high rise and effortless wide leg.",
      category: "women",
      colors: ["Indigo", "Black", "Light Wash"],
      sizes: ["24", "26", "28", "30", "32"],
      active: true
    },
    {
      id: 9005,
      name: "Urban Oversized Hoodie",
      price: 3890,
      image_url: "https://images.unsplash.com/photo-1556821840-3a63f95609a7?w=600&h=750&fit=crop",
      description: "Heavyweight fleece hoodie with dropped shoulders and roomy street fit.",
      category: "streetwear",
      colors: ["Black", "Heather Grey", "Electric Lime"],
      sizes: ["S", "M", "L", "XL", "XXL"],
      active: true
    },
    {
      id: 9006,
      name: "Cargo Utility Pants",
      price: 4990,
      image_url: "https://images.unsplash.com/photo-1624378439575-d8705ad7ae80?w=600&h=750&fit=crop",
      description: "Technical cargo pants with multiple pockets and adjustable hem.",
      category: "streetwear",
      colors: ["Olive", "Black", "Khaki"],
      sizes: ["S", "M", "L", "XL"],
      active: true
    },
    {
      id: 9007,
      name: "Minimal Leather Belt",
      price: 2190,
      image_url: "https://images.unsplash.com/photo-1624222247344-550fb60583fd?w=600&h=750&fit=crop",
      description: "Full-grain leather belt with brushed metal buckle. Timeless essential.",
      category: "accessories",
      colors: ["Black", "Brown"],
      sizes: ["S", "M", "L"],
      active: true
    },
    {
      id: 9008,
      name: "Structured Crossbody Bag",
      price: 5490,
      image_url: "https://images.unsplash.com/photo-1548036328-c9fa89d128ac?w=600&h=750&fit=crop",
      description: "Compact structured bag in pebbled leather with adjustable strap.",
      category: "accessories",
      colors: ["Tan", "Black", "Cream"],
      sizes: ["One Size"],
      active: true
    }
  ],
  notice: {
    title: "New Season Drop",
    message: "Explore the latest arrivals in menswear, womenswear and streetwear. Free delivery on orders over NPR 5,000.",
    image_url: "",
    button_text: "Shop Now",
    button_url: "/shop.html",
    notice_type: "banner",
    enabled: true
  },
  settings: {
    logo_url: "",
    favicon_url: "",
    brand_name: "ABC Clothing",
    facebook_url: "",
    instagram_url: "",
    whatsapp: ""
  }
};
