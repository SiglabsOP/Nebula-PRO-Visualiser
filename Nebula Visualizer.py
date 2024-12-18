import asyncio
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QTabWidget, QLabel, QScrollArea, QHBoxLayout
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
import plotly.express as px
import pandas as pd
import sys
import gc
from cryptography.fernet import Fernet
import io  # Add this import for StringIO
import ctypes

# Path to your encrypted agenda file and the key
file_path = "userdata/nebula-agenda.txt"
key_path = "encryption.key"

# Decrypt the encrypted file content using the Fernet key
def load_and_decrypt_file(file_path, key_path):
    with open(key_path, "rb") as key_file:
        fernet_key = key_file.read()
    fernet = Fernet(fernet_key)
    
    with open(file_path, "rb") as encrypted_file:
        encrypted_data = encrypted_file.read()
    
    decrypted_data = fernet.decrypt(encrypted_data)
    return decrypted_data.decode("utf-8")
    
 
def secure_zero_memory(data):
    """Securely overwrite the memory of a string or bytearray."""
    if isinstance(data, str):
        # Convert string to a byte buffer
        buf = ctypes.create_string_buffer(data.encode())
        # Overwrite memory with null bytes
        ctypes.memset(ctypes.addressof(buf), 0, len(data))
    elif isinstance(data, bytes):
        # For bytes, directly create a byte buffer
        buf = ctypes.create_string_buffer(data)
        ctypes.memset(ctypes.addressof(buf), 0, len(data))

 

class WorkerThread(QThread):
    data_loaded = pyqtSignal(pd.DataFrame)  # Signal emitted when data is ready

    def __init__(self, file_path, key_path):
        super().__init__()
        self.file_path = file_path
        self.key_path = key_path

    def run(self):
        try:
            # Decrypt and load the data
            decrypted_text = load_and_decrypt_file(self.file_path, self.key_path)

           #  print("Decrypted Text Preview:", decrypted_text[:500])  # Debug: Show preview of decrypted text

            # Detect JSON format
            if decrypted_text.strip().startswith("{") or decrypted_text.strip().startswith("["):
                # Parse as JSON if the file contains JSON data
                data = pd.read_json(io.StringIO(decrypted_text))
            else:
                # Parse as CSV, automatically detect headers
                data = pd.read_csv(io.StringIO(decrypted_text))

          #  print("DataFrame Preview:", data.head())  # Debug: Show preview of the DataFrame

            # Normalize column names to match expected format
            data.rename(
                columns={"date": "Date", "time": "Time", "description": "Description"},
                inplace=True
            )

            # Ensure required columns exist
            if not all(col in data.columns for col in ["Date", "Time", "Description"]):
                raise ValueError("The decrypted file does not contain the expected columns: 'Date', 'Time', 'Description'.")

            # Convert columns to appropriate data types
            data["Date"] = pd.to_datetime(data["Date"], errors='coerce')
            data["Time"] = pd.to_datetime(data["Time"], format='%H:%M', errors='coerce').dt.time

            # Drop rows with invalid dates or times
            data = data.dropna(subset=["Date", "Time"])

            # Emit the loaded data
            self.data_loaded.emit(data)

        except Exception as e:
            print(f"Error processing file: {e}")
            self.data_loaded.emit(pd.DataFrame())  # Emit an empty DataFrame on error
        finally:
            # Securely overwrite and delete decrypted_text
            secure_zero_memory(decrypted_text)
            del decrypted_text
            gc.collect()  # Force garbage collection



# Asynchronous Functions
async def generate_insights_async(data):
    await asyncio.sleep(0)  # Simulate async processing
    today = pd.Timestamp.now().normalize()
    upcoming = data[data["Date"] >= today]
    historical = data[data["Date"] < today]

    summary = {
        "Total Appointments": len(data),
        "Upcoming Appointments": len(upcoming),
        "Historical Appointments": len(historical),
        "Categories": data["Description"].value_counts().to_dict(),
    }
    return summary, upcoming, historical

async def create_plots_async(data):
    await asyncio.sleep(0)  # Simulate async processing
    date_range = pd.date_range(data["Date"].min(), data["Date"].max())
    daily_counts = data["Date"].value_counts().reindex(date_range, fill_value=0).sort_index()
    monthly_counts = data.groupby(data["Date"].dt.to_period("M")).size().reindex(
        pd.period_range(data["Date"].min().to_period("M"), data["Date"].max().to_period("M")),
        fill_value=0
    )

    line_chart_monthly = px.line(
        x=monthly_counts.index.astype(str), y=monthly_counts.values,
        labels={"x": "Month", "y": "Appointments"},
        title="Appointment Trends Over Time (Monthly)"
    )

    monthly_counts_bar = px.bar(
        monthly_counts, x=monthly_counts.index.astype(str), y=monthly_counts.values,
        labels={"x": "Month", "y": "Appointments"},
        title="Appointments Per Month"
    )

    category_counts = data["Description"].value_counts()
    pie_chart = px.pie(
        category_counts, values=category_counts.values, names=category_counts.index,
        title="Appointments by Category"
    )

    line_chart_monthly_html = line_chart_monthly.to_html(full_html=False, include_plotlyjs="cdn")
    monthly_counts_bar_html = monthly_counts_bar.to_html(full_html=False, include_plotlyjs="cdn")
    pie_chart_html = pie_chart.to_html(full_html=False, include_plotlyjs="cdn")

    return line_chart_monthly_html, monthly_counts_bar_html, pie_chart_html

# Main GUI Window
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nebula Visualizer (c) SIG Labs 2024")
        self.setGeometry(100, 100, 1200, 800)
        
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        
        # Initialize worker thread for data loading
        self.worker_thread = WorkerThread(file_path, key_path)
        self.worker_thread.data_loaded.connect(self.on_data_loaded)
        self.worker_thread.start()

        self.insights = None
        self.plots = None

        # Placeholder until data is loaded
        self.init_loading_screen()

    def init_loading_screen(self):
        loading_tab = QWidget()
        loading_layout = QVBoxLayout()
        loading_label = QLabel("Loading data... Please wait.")
        loading_label.setAlignment(Qt.AlignCenter)
        loading_layout.addWidget(loading_label)
        loading_tab.setLayout(loading_layout)
        self.tabs.addTab(loading_tab, "Loading")

    @pyqtSlot(pd.DataFrame)
    def on_data_loaded(self, data):
        asyncio.run(self.process_data_async(data))

    async def process_data_async(self, data):
        # Remove loading tab
        self.tabs.clear()

        # Generate insights asynchronously
        self.insights, upcoming, historical = await generate_insights_async(data)

        # Generate plots asynchronously
        self.plots = await create_plots_async(data)

        # Initialize GUI Tabs
        self.init_dashboard_tab()
        self.init_graphs_tab()
        self.init_raw_data_tab(data)
        self.init_copyright_tab()

    def closeEvent(self, event):
        """Ensure memory cleanup before program exit."""
        self.worker_thread.quit()
        self.worker_thread.wait()
        self.cleanup_memory()
        super().closeEvent(event)

    def cleanup_memory(self):
        """Securely wipe sensitive data from memory."""
        self.insights = None
        self.plots = None
        gc.collect()

    def init_dashboard_tab(self):
        dashboard_tab = QWidget()
        scroll_area = QScrollArea()  # Add a scroll area
        scroll_area.setWidgetResizable(True)  # Make scroll area adaptable

        scroll_content = QWidget()  # Content widget for the scroll area
        dashboard_layout = QVBoxLayout(scroll_content)

        # Display insights
        insight_layout = QHBoxLayout()
        for key, value in self.insights.items():
            if key != "Categories":
                label = QLabel(f"<b>{key}:</b> {value}")
                insight_layout.addWidget(label)
        dashboard_layout.addLayout(insight_layout)

        # Display categories
        category_layout = QVBoxLayout()
        category_label = QLabel("<b>Categories:</b>")
        category_layout.addWidget(category_label)
        for category, count in self.insights["Categories"].items():
            category_item = QLabel(f"{category}: {count}")
            category_layout.addWidget(category_item)
        dashboard_layout.addLayout(category_layout)

        scroll_area.setWidget(scroll_content)  # Add content to scroll area
        dashboard_tab_layout = QVBoxLayout(dashboard_tab)
        dashboard_tab_layout.addWidget(scroll_area)
        dashboard_tab.setLayout(dashboard_tab_layout)

        self.tabs.addTab(dashboard_tab, "Dashboard")

    def init_graphs_tab(self):
        graphs_tab = QWidget()
        graphs_layout = QVBoxLayout()
        for chart_html in self.plots:
            chart_view = QWebEngineView()
            chart_view.setHtml(chart_html)
            graphs_layout.addWidget(chart_view)
        graphs_tab.setLayout(graphs_layout)
        self.tabs.addTab(graphs_tab, "Graphs")

    def init_raw_data_tab(self, data):
        data_tab = QWidget()
        scroll_area = QScrollArea()  # Add a scroll area
        scroll_area.setWidgetResizable(True)  # Make scroll area adaptable

        scroll_content = QWidget()  # Content widget for the scroll area
        scroll_layout = QVBoxLayout(scroll_content)

        # Sort data by the "Date" column
        sorted_data = data.sort_values(by="Date")

        # Convert sorted data to string and display
        raw_data_label = QLabel(sorted_data.to_string(index=False))
        raw_data_label.setWordWrap(True)  # Ensure text wraps correctly
        scroll_layout.addWidget(raw_data_label)

        scroll_area.setWidget(scroll_content)  # Add content to scroll area
        data_tab_layout = QVBoxLayout(data_tab)
        data_tab_layout.addWidget(scroll_area)
        data_tab.setLayout(data_tab_layout)

        self.tabs.addTab(data_tab, "Live Data")

    def init_copyright_tab(self):
        copyright_tab = QWidget()
        copyright_layout = QVBoxLayout()
        copyright_label = QLabel("<b>(c) 2024 Peter De Ceuster Nebula Visualizer v 30.1</b>")
        copyright_layout.addWidget(copyright_label)
        copyright_tab.setLayout(copyright_layout)
        self.tabs.addTab(copyright_tab, "Copyright")

if __name__ == '__main__':
    app = QApplication(sys.argv)

    # Set global font
    font = QFont("Segoe UI", 16)
    app.setFont(font)

    window = MainWindow()
    window.showMaximized()

    sys.exit(app.exec_())
