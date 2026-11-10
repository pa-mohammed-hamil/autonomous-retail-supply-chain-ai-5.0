"""
Store Demand Clustering for Assortment Planning
Groups stores by similar demand patterns and demographics for optimized assortments.
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Tuple, Optional
from sklearn.cluster import KMeans, DBSCAN
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score, davies_bouldin_score
import logging

logger = logging.getLogger(__name__)


class StoreDemandClusterer:
    """
    Cluster stores based on demand patterns, demographics, and performance characteristics.
    
    Used to create store groupings that can share similar assortments.
    """
    
    def __init__(
        self,
        n_clusters: int = 5,
        algorithm: str = "kmeans",  # kmeans, dbscan, hierarchical
        random_state: int = 42
    ):
        self.n_clusters = n_clusters
        self.algorithm = algorithm
        self.random_state = random_state
        self.scaler = StandardScaler()
        self.pca = PCA(n_components=0.95)  # Retain 95% variance
        self.model = None
        self.cluster_profiles = {}
        
    def prepare_features(self, store_data: pd.DataFrame) -> pd.DataFrame:
        """
        Prepare feature matrix for clustering.
        
        Features include:
        - Demographics (income, population, age distribution)
        - Performance metrics (sales per sqft, inventory turnover)
        - Category preferences (sales mix)
        - Store characteristics (size, location type)
        """
        
        features = pd.DataFrame()
        
        # Demographic features
        features["median_income"] = store_data["median_income"]
        features["population"] = store_data["population"]
        features["avg_household_size"] = store_data["avg_household_size"]
        features["urban_density_score"] = store_data.get("urban_density_score", 50)
        
        # Age distribution (one-hot or continuous)
        for age_group in ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]:
            col_name = f"age_{age_group.replace('-', '_')}"
            features[col_name] = store_data.get(f"age_pct_{age_group}", 0)
        
        # Performance features
        features["sales_per_sqft"] = store_data["sales_per_sqft"]
        features["inventory_turnover"] = store_data["inventory_turnover"]
        features["stockout_rate"] = store_data["stockout_rate"]
        features["margin_pct"] = store_data.get("margin_pct", 25)
        
        # Category preferences
        categories = ["Produce", "Dairy", "Bakery", "Meat", "Grocery", "Other"]
        for category in categories:
            features[f"category_pct_{category.lower()}"] = store_data.get(
                f"category_sales_pct_{category}", 0
            )
        
        # Store characteristics
        features["store_size_sqft"] = store_data["store_size_sqft"]
        features["sku_count"] = store_data["sku_count"]
        
        return features
    
    def fit(self, store_data: pd.DataFrame) -> "StoreDemandClusterer":
        """
        Fit clustering model to store data.
        
        Args:
            store_data: DataFrame with store features
            
        Returns:
            self for method chaining
        """
        
        logger.info(f"Clustering {len(store_data)} stores using {self.algorithm}")
        
        # Prepare features
        features = self.prepare_features(store_data)
        
        # Handle missing values
        features = features.fillna(features.median())
        
        # Scale features
        features_scaled = self.scaler.fit_transform(features)
        
        # Optional dimensionality reduction
        if features_scaled.shape[1] > 10:
            features_scaled = self.pca.fit_transform(features_scaled)
            logger.info(f"Reduced to {features_scaled.shape[1]} components (PCA)")
        
        # Fit clustering model
        if self.algorithm == "kmeans":
            self.model = KMeans(
                n_clusters=self.n_clusters,
                random_state=self.random_state,
                n_init=10
            )
        elif self.algorithm == "dbscan":
            self.model = DBSCAN(eps=0.5, min_samples=3)
        else:
            raise ValueError(f"Unknown algorithm: {self.algorithm}")
        
        cluster_labels = self.model.fit_predict(features_scaled)
        
        # Evaluate clustering quality
        if len(set(cluster_labels)) > 1:
            silhouette = silhouette_score(features_scaled, cluster_labels)
            davies_bouldin = davies_bouldin_score(features_scaled, cluster_labels)
            logger.info(f"Silhouette Score: {silhouette:.3f}")
            logger.info(f"Davies-Bouldin Index: {davies_bouldin:.3f}")
        
        # Create cluster profiles
        store_data["cluster"] = cluster_labels
        self._create_cluster_profiles(store_data)
        
        return self
    
    def _create_cluster_profiles(self, store_data: pd.DataFrame) -> None:
        """Create descriptive profiles for each cluster."""
        
        for cluster_id in store_data["cluster"].unique():
            if cluster_id == -1:  # DBSCAN noise points
                continue
                
            cluster_stores = store_data[store_data["cluster"] == cluster_id]
            
            profile = {
                "cluster_id": int(cluster_id),
                "store_count": len(cluster_stores),
                "stores": cluster_stores["store_id"].tolist(),
                "characteristics": {
                    "median_income": cluster_stores["median_income"].mean(),
                    "avg_population": cluster_stores["population"].mean(),
                    "avg_store_size_sqft": cluster_stores["store_size_sqft"].mean(),
                    "avg_sales_per_sqft": cluster_stores["sales_per_sqft"].mean(),
                    "avg_inventory_turnover": cluster_stores["inventory_turnover"].mean(),
                    "avg_sku_count": cluster_stores["sku_count"].mean()
                },
                "dominant_categories": self._get_dominant_categories(cluster_stores),
                "demographic_profile": self._get_demographic_profile(cluster_stores)
            }
            
            # Assign cluster name based on characteristics
            profile["name"] = self._generate_cluster_name(profile)
            
            self.cluster_profiles[cluster_id] = profile
    
    def _get_dominant_categories(self, cluster_stores: pd.DataFrame) -> List[str]:
        """Identify dominant product categories for a cluster."""
        
        categories = []
        category_cols = [col for col in cluster_stores.columns if col.startswith("category_sales_pct_")]
        
        for col in category_cols:
            avg_pct = cluster_stores[col].mean()
            if avg_pct > 15:  # Significant category (>15% of sales)
                category_name = col.replace("category_sales_pct_", "").title()
                categories.append(category_name)
        
        return categories
    
    def _get_demographic_profile(self, cluster_stores: pd.DataFrame) -> str:
        """Generate demographic profile description for a cluster."""
        
        median_income = cluster_stores["median_income"].mean()
        
        if median_income > 80000:
            income_segment = "affluent"
        elif median_income > 60000:
            income_segment = "middle-income"
        else:
            income_segment = "value-focused"
        
        # Determine dominant age group
        age_cols = [col for col in cluster_stores.columns if col.startswith("age_pct_")]
        if age_cols:
            dominant_age_col = max(age_cols, key=lambda col: cluster_stores[col].mean())
            dominant_age = dominant_age_col.replace("age_pct_", "").replace("_", "-")
        else:
            dominant_age = "mixed-age"
        
        return f"{income_segment}_{dominant_age}"
    
    def _generate_cluster_name(self, profile: Dict[str, Any]) -> str:
        """Generate descriptive name for cluster."""
        
        chars = profile["characteristics"]
        
        # Income-based naming
        if chars["median_income"] > 80000:
            income_label = "Premium"
        elif chars["median_income"] > 60000:
            income_label = "Standard"
        else:
            income_label = "Value"
        
        # Location-based naming (simplified)
        if chars["avg_store_size_sqft"] < 4000:
            location_label = "Urban"
        elif chars["avg_store_size_sqft"] > 8000:
            location_label = "Suburban"
        else:
            location_label = "Community"
        
        return f"{location_label} {income_label}"
    
    def predict(self, store_data: pd.DataFrame) -> np.ndarray:
        """
        Predict cluster assignments for new stores.
        
        Args:
            store_data: DataFrame with store features
            
        Returns:
            Array of cluster labels
        """
        
        if self.model is None:
            raise ValueError("Model not fitted. Call fit() first.")
        
        features = self.prepare_features(store_data)
        features = features.fillna(features.median())
        features_scaled = self.scaler.transform(features)
        
        if hasattr(self.pca, "components_"):
            features_scaled = self.pca.transform(features_scaled)
        
        return self.model.predict(features_scaled)
    
    def get_cluster_profile(self, cluster_id: int) -> Dict[str, Any]:
        """Get detailed profile for a specific cluster."""
        return self.cluster_profiles.get(cluster_id, {})
    
    def get_all_profiles(self) -> List[Dict[str, Any]]:
        """Get profiles for all clusters."""
        return list(self.cluster_profiles.values())
    
    def recommend_assortment_size(self, cluster_id: int) -> int:
        """Recommend optimal SKU count for a cluster."""
        
        profile = self.cluster_profiles.get(cluster_id, {})
        if not profile:
            return 1000  # Default
        
        chars = profile["characteristics"]
        
        # Base SKU count on store size and sales performance
        base_skus = chars["avg_store_size_sqft"] * 0.2  # 0.2 SKUs per sqft
        
        # Adjust for performance
        performance_factor = chars["avg_sales_per_sqft"] / 250  # Normalized to $250/sqft
        adjusted_skus = base_skus * performance_factor
        
        # Clamp to reasonable range
        return int(np.clip(adjusted_skus, 500, 3000))
    
    def get_similar_stores(
        self,
        store_id: str,
        store_data: pd.DataFrame,
        top_n: int = 5
    ) -> List[str]:
        """
        Find stores most similar to the given store.
        
        Useful for:
        - Benchmarking
        - Test group selection for new products
        - Best practice sharing
        """
        
        if store_id not in store_data["store_id"].values:
            raise ValueError(f"Store {store_id} not found in data")
        
        # Get cluster of target store
        target_cluster = store_data[store_data["store_id"] == store_id]["cluster"].values[0]
        
        # Get all stores in same cluster
        cluster_stores = store_data[store_data["cluster"] == target_cluster]
        
        # Calculate similarity within cluster (using euclidean distance)
        target_features = self.prepare_features(
            store_data[store_data["store_id"] == store_id]
        ).values[0]
        
        similarities = []
        for _, store in cluster_stores.iterrows():
            if store["store_id"] == store_id:
                continue
            
            store_features = self.prepare_features(
                pd.DataFrame([store])
            ).values[0]
            
            distance = np.linalg.norm(target_features - store_features)
            similarities.append((store["store_id"], distance))
        
        # Sort by similarity (lower distance = more similar)
        similarities.sort(key=lambda x: x[1])
        
        return [store_id for store_id, _ in similarities[:top_n]]


def optimize_cluster_count(
    store_data: pd.DataFrame,
    min_clusters: int = 3,
    max_clusters: int = 10
) -> Tuple[int, Dict[str, Any]]:
    """
    Determine optimal number of clusters using elbow method and silhouette analysis.
    
    Returns:
        Tuple of (optimal_k, metrics_by_k)
    """
    
    metrics = {}
    
    for k in range(min_clusters, max_clusters + 1):
        clusterer = StoreDemandClusterer(n_clusters=k)
        clusterer.fit(store_data)
        
        features = clusterer.prepare_features(store_data)
        features_scaled = clusterer.scaler.transform(features.fillna(features.median()))
        
        if hasattr(clusterer.pca, "components_"):
            features_scaled = clusterer.pca.transform(features_scaled)
        
        labels = clusterer.model.labels_
        
        inertia = clusterer.model.inertia_ if hasattr(clusterer.model, "inertia_") else 0
        silhouette = silhouette_score(features_scaled, labels)
        davies_bouldin = davies_bouldin_score(features_scaled, labels)
        
        metrics[k] = {
            "inertia": inertia,
            "silhouette": silhouette,
            "davies_bouldin": davies_bouldin
        }
    
    # Select optimal k (highest silhouette score)
    optimal_k = max(metrics.keys(), key=lambda k: metrics[k]["silhouette"])
    
    logger.info(f"Optimal cluster count: {optimal_k}")
    logger.info(f"Metrics: {metrics[optimal_k]}")
    
    return optimal_k, metrics
