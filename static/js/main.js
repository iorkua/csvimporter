// Main JavaScript for CSV Importer
document.addEventListener('DOMContentLoaded', function() {
    // Initialize the application
    initializeApp();
});

function initializeApp() {
    // Set active navigation
    setActiveNavigation();
    
    // Initialize tooltips
    initializeTooltips();
    
    // Add fade-in animation to content
    animateContent();
    
    console.log('CSV Importer application initialized');
}

function setActiveNavigation() {
    // Get current path
    const currentPath = window.location.pathname;
    
    // Remove active class from all nav links
    document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.remove('active');
    });
    
    // Add active class to current page link
    const activeLink = document.querySelector(`a[href="${currentPath}"]`);
    if (activeLink) {
        activeLink.classList.add('active');
    } else {
        // Default to dashboard if no match
        const dashboardLink = document.querySelector('a[href="/"]');
        if (dashboardLink) {
            dashboardLink.classList.add('active');
        }
    }
}

function initializeTooltips() {
    // Initialize Bootstrap tooltips if they exist
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
}

function animateContent() {
    // Add fade-in animation to main content
    const contentArea = document.querySelector('.content-area');
    if (contentArea) {
        contentArea.classList.add('fade-in');
    }
}

// Sidebar toggle for mobile
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    if (sidebar) {
        sidebar.classList.toggle('show');
    }
}

// Utility function to show loading state
function showLoading(element) {
    if (element) {
        element.classList.add('loading');
    }
}

// Utility function to hide loading state
function hideLoading(element) {
    if (element) {
        element.classList.remove('loading');
    }
}

// Utility function to show notifications
function showNotification(message, type = 'info') {
    // This would integrate with a notification system
    console.log(`${type.toUpperCase()}: ${message}`);
}

// Export functions for use in other files
window.CSVImporter = {
    showLoading,
    hideLoading,
    showNotification,
    toggleSidebar
};