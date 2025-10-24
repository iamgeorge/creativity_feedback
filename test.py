import numpy as np
import matplotlib.pyplot as plt

# Simulation parameters
np.random.seed(42)
steps = 30   # number of tasks or time steps
baseline = 40  # starting creativity score

# No feedback condition
no_feedback = [baseline]
for t in range(1, steps):
    # small random growth with noise
    growth = np.random.normal(loc=0.5, scale=2.0)
    no_feedback.append(max(0, no_feedback[-1] + growth))

# With feedback condition
with_feedback = [baseline]
for t in range(1, steps):
    # higher growth with reduced noise due to supportive feedback
    growth = np.random.normal(loc=1.2, scale=1.0)
    with_feedback.append(max(0, with_feedback[-1] + growth))

# Plotting the curves
plt.figure(figsize=(10,6))
plt.plot(no_feedback, label="No Feedback", color="red", linestyle="--")
plt.plot(with_feedback, label="With Feedback", color="blue", linewidth=2)

plt.title("Simulated Student Creativity Curve")
plt.xlabel("Task / Time Step")
plt.ylabel("Creativity Score")
plt.legend()
plt.grid(True)
plt.show()
plt.savefig("creativity_curve.png")
