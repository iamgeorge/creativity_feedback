import numpy as np
import matplotlib.pyplot as plt

# Parameters
np.random.seed(42)
steps = 30   # number of tasks / time steps
baseline = 2.0  # starting creativity score (1–5 scale)

# Helper function to keep scores in [1, 5]
def clip_score(score):
    return max(1, min(5, score))

# No feedback condition
no_feedback = [baseline]
for t in range(1, steps):
    growth = np.random.normal(loc=0.05, scale=0.3)  # small growth, more noise
    no_feedback.append(clip_score(no_feedback[-1] + growth))

# With feedback condition
with_feedback = [baseline]
for t in range(1, steps):
    growth = np.random.normal(loc=0.15, scale=0.2)  # larger growth, less noise
    with_feedback.append(clip_score(with_feedback[-1] + growth))

# Plot
plt.figure(figsize=(10,6))
plt.plot(no_feedback, label="No Feedback", color="red", linestyle="--")
plt.plot(with_feedback, label="With Feedback", color="blue", linewidth=2)

plt.title("Simulated Creativity Curve (Scale 1–5)")
plt.xlabel("Task / Time Step")
plt.ylabel("Creativity Score (1–5)")
plt.ylim(1, 5.2)
plt.legend()
plt.grid(True)
plt.show()
plt.savefig("creativity_curve.png")