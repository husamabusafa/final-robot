import { motion } from "framer-motion";

const COMPANIES = ["تيتكو", "التعليمية", "تطوير للمباني", "رافد"];

export function IdleScreen() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="flex h-full flex-col items-center justify-center px-[8vw] text-center"
    >
      <div className="relative mb-10 h-24 w-24">
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            className="absolute inset-0 rounded-full border-2 border-c1"
            animate={{ scale: [1, 1.6], opacity: [0.55, 0] }}
            transition={{ duration: 2.6, delay: i * 0.85, repeat: Infinity, ease: "easeOut" }}
          />
        ))}
        <span className="absolute inset-[30%] rounded-full bg-gradient-to-br from-c1 to-c2" />
      </div>

      <h1 className="gradient-text text-[clamp(30px,4vw,64px)] font-black leading-tight">
        أهلًا! أنا روبوتكم الذكي
      </h1>
      <p className="mt-5 max-w-3xl text-[clamp(15px,1.5vw,26px)] leading-loose text-dim">
        اسألوني عن منظومة تطوير التعليم وشركاتها، وأقدر أعرض لكم الإحصائيات
        والرسوم البيانية والفيديوهات على هذه الشاشة.
      </p>

      <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
        {COMPANIES.map((name, i) => (
          <motion.span
            key={name}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 * i + 0.2, duration: 0.5 }}
            className="rounded-full border border-line bg-card/60 px-5 py-2
                       text-[clamp(13px,1.2vw,20px)] font-bold text-c1 backdrop-blur"
          >
            {name}
          </motion.span>
        ))}
      </div>

      <p className="mt-12 text-[clamp(12px,1.1vw,19px)] text-dim/60">
        جرّبوا تقولون لي: «اعرض لي أرقام رافد» أو «قارن بين الشركات»
      </p>
    </motion.div>
  );
}
