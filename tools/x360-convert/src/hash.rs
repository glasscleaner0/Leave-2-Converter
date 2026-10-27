// SHA-1, implemented from the algorithm in FIPS PUB 180-4.
pub struct Sha1 {
    state: [u32; 5],
    bytes: u64,
    tail: Vec<u8>,
}
impl Sha1 {
    pub fn new() -> Self {
        Self {
            state: [0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476, 0xc3d2e1f0],
            bytes: 0,
            tail: Vec::new(),
        }
    }
    fn block(&mut self, b: &[u8]) {
        let mut w = [0u32; 80];
        for (i, c) in b.chunks_exact(4).enumerate() {
            w[i] = u32::from_be_bytes(c.try_into().unwrap());
        }
        for i in 16..80 {
            w[i] = (w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16]).rotate_left(1);
        }
        let [mut a, mut b, mut c, mut d, mut e] = self.state;
        for (i, wi) in w.iter().enumerate() {
            let (f, k) = match i {
                0..20 => ((b & c) | (!b & d), 0x5a827999u32),
                20..40 => (b ^ c ^ d, 0x6ed9eba1),
                40..60 => ((b & c) | (b & d) | (c & d), 0x8f1bbcdc),
                _ => (b ^ c ^ d, 0xca62c1d6),
            };
            let t = a
                .rotate_left(5)
                .wrapping_add(f)
                .wrapping_add(e)
                .wrapping_add(k)
                .wrapping_add(*wi);
            e = d;
            d = c;
            c = b.rotate_left(30);
            b = a;
            a = t;
        }
        for (s, v) in self.state.iter_mut().zip([a, b, c, d, e]) {
            *s = s.wrapping_add(v);
        }
    }
    pub fn update(&mut self, mut b: &[u8]) {
        self.bytes += b.len() as u64;
        if !self.tail.is_empty() {
            let n = (64 - self.tail.len()).min(b.len());
            self.tail.extend_from_slice(&b[..n]);
            b = &b[n..];
            if self.tail.len() == 64 {
                let t = std::mem::take(&mut self.tail);
                self.block(&t);
            }
        }
        while b.len() >= 64 {
            self.block(&b[..64]);
            b = &b[64..];
        }
        self.tail.extend_from_slice(b);
    }
    pub fn finish(mut self) -> [u8; 20] {
        let bits = self.bytes * 8;
        let mut t = std::mem::take(&mut self.tail);
        t.push(0x80);
        while t.len() % 64 != 56 {
            t.push(0);
        }
        t.extend_from_slice(&bits.to_be_bytes());
        for b in t.chunks_exact(64) {
            self.block(b);
        }
        let mut r = [0; 20];
        for (c, s) in r.chunks_exact_mut(4).zip(self.state) {
            c.copy_from_slice(&s.to_be_bytes());
        }
        r
    }
}
pub fn sha1(b: &[u8]) -> [u8; 20] {
    let mut h = Sha1::new();
    h.update(b);
    h.finish()
}
pub fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn published_vectors() {
        assert_eq!(hex(&sha1(b"")), "da39a3ee5e6b4b0d3255bfef95601890afd80709");
        assert_eq!(
            hex(&sha1(b"abc")),
            "a9993e364706816aba3e25717850c26c9cd0d89d"
        );
        assert_eq!(
            hex(&sha1(&vec![b'a'; 1_000_000])),
            "34aa973cd4c4daa4f61eeb2bdbad27316534016f"
        );
        let mut h = Sha1::new();
        for _ in 0..1000 {
            h.update(&[b'a'; 1000]);
        }
        assert_eq!(hex(&h.finish()), "34aa973cd4c4daa4f61eeb2bdbad27316534016f");
    }
}
