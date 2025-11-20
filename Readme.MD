# ML-Based Rebate Simulator

A powerful, AI-driven tool to optimize customer rebate grids. This application uses Machine Learning to predict how rebates drive revenue growth and finds the optimal rebate structure to maximize **Net Profit**.

## 🚀 Key Features

*   **ML Elasticity Model**: Automatically trains a Linear Regression model on your data to predict the "elasticity" of your customers (how much they grow when given a rebate).
*   **Mathematical Optimization**: Uses `scipy.optimize` (Trust-Constr method) to find the mathematical maximum for Net Revenue.
*   **Dynamic Configuration**:
    *   Define your own **Volume** and **Growth** tiers on the fly.
    *   Adjust **Elasticity** assumptions manually or let the ML model decide.
*   **Strict Business Rules**:
    *   **0% Rebate** for low-growth customers (<8%).
    *   **Monotonicity**: Rebates always increase with higher volume/growth.
    *   **Bounds**: Rates capped between 1% and 15%.

## 🛠️ How to Run

1.  **Install Dependencies**:
    ```bash
    pip install pandas numpy scipy scikit-learn flask
    ```

2.  **Start the Application**:
    ```bash
    python optimized_app.py
    ```

3.  **Open in Browser**:
    Go to [http://127.0.0.1:5000](http://127.0.0.1:5000)

## 📚 How It Works

The optimizer balances two competing forces:
1.  **Cost**: Higher rebates cost more money.
2.  **Growth**: Higher rebates drive more revenue (predicted by ML).

It finds the "sweet spot" where the extra revenue outweighs the rebate cost.

👉 **[Click here for ML Model Walkthrough](CALCULATION_WALKTHROUGH.md)**
👉 **[Click here for Standard Model Walkthrough](CALCULATION_WALKTHROUGH_STANDARD.md)**
(These documents explain the exact math and logic used by the program).

## 📂 Project Structure

*   `optimized_app.py`: The Flask backend that runs the UI and connects to the optimizer.
*   `ML_Rebate_Optimizer.py`: The core logic containing the ML model and optimization algorithms.
*   `templates/index.html`: The modern, dark-mode user interface.
*   `static/`: CSS and JavaScript files for the frontend.
*   `DummyDataGpot2.csv`: The input dataset.
