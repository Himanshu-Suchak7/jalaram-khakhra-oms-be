# Database Migration Instructions

Since new fields (`address` and `city`) have been added to the `Customers` table, you need to run a database migration to update your database schema.

## Alembic Migration Commands

Follow these steps in your terminal (make sure you are in the `oms backend` directory and your virtual environment is active):

1. **Generate the migration script:**
   ```powershell
   alembic revision --autogenerate -m "Add address and city to customers"
   ```

2. **Apply the migration to your database:**
   ```powershell
   alembic upgrade head
   ```

---
**Note:** If you encounter any issues, ensure your `.env` file has the correct `DATABASE_URL` configured.
